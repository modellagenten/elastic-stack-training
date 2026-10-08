"""Kommandozeile: live, backfill, scenario, profiles, formats."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from . import __version__
from .engine import Engine, validate_profile
from .formats import FORMATS
from .model import diurnal
from .scenarios import SCENARIOS, create
from .sinks import BulkSink, FileSink, StdoutSink

GENERATOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(GENERATOR_DIR, "profiles")
REPO_DIR = os.path.dirname(GENERATOR_DIR)
CONTROL_FILE = ".loggen-control.json"
HEARTBEAT_FILE = ".loggen-heartbeat"

EPILOG = """
Beispiele:
  python loggen.py live --profile alerting --rate 20
  python loggen.py live --profile alerting --scenario brute-force:2m:5m
  python loggen.py scenario error-spike --duration 10m --param service=checkout --param error_rate=0.5
  python loggen.py scenario --status
  python loggen.py backfill --profile alerting --from now-1d --to now --stdout | head
  python loggen.py backfill --profile columnar-demo --events 1000000 --es http://localhost:9200
"""


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def now_utc():
    return datetime.now(timezone.utc)


def parse_duration(text):
    if text in (None, "", "0"):
        return 0.0
    m = re.fullmatch(r"\+?(\d+(?:\.\d+)?)([smhd]?)", str(text).strip())
    if not m:
        raise argparse.ArgumentTypeError(f"Ungültige Dauer {text!r} (Beispiele: 30s, 5m, 2h, 7d)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def parse_time(text, ref=None):
    ref = ref or now_utc()
    text = text.strip()
    if text == "now":
        return ref
    m = re.fullmatch(r"now([+-])(.+)", text)
    if m:
        delta = timedelta(seconds=parse_duration(m.group(2)))
        return ref - delta if m.group(1) == "-" else ref + delta
    ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def parse_params(items):
    params = {}
    for item in items or []:
        for part in item.split(","):
            if "=" not in part:
                raise SystemExit(f"Parameter {part!r} muss die Form key=value haben")
            key, value = part.split("=", 1)
            params[key.strip()] = value.strip()
    return params


def fmt_params(params):
    return " ".join(f"{k}={v}" for k, v in (params or {}).items())


def read_dotenv():
    """Liest ELASTIC_* aus der .env der Schulungsumgebung, falls nicht im Environment gesetzt."""
    values = {}
    path = os.path.join(REPO_DIR, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r'\s*([A-Z_]+)\s*=\s*"?([^"\n]*)"?', line)
                if m:
                    values[m.group(1)] = m.group(2)
    return values


def load_profile(name):
    path = name if os.path.isfile(name) else os.path.join(PROFILE_DIR, f"{name}.json")
    if not os.path.isfile(path):
        available = ", ".join(sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json")))
        raise SystemExit(f"Profil {name!r} nicht gefunden. Verfügbar: {available}")
    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)
    errors = validate_profile(profile)
    if errors:
        raise SystemExit("Fehler im Profil:\n  " + "\n  ".join(errors))
    return profile


def default_out():
    return os.environ.get("LOGGEN_OUT") or os.path.join(REPO_DIR, "data", "generated")


def build_sinks(args, profile, live):
    sinks = []
    if args.stdout:
        sinks.append(StdoutSink(with_stream_name=args.show_stream))
    if args.es:
        env = read_dotenv()
        targets = args.targets.split(",") if args.targets else profile.get("targets")
        if not targets:
            raise SystemExit("--es benötigt --targets (oder 'targets' im Profil)")
        password = args.password or os.environ.get("ELASTIC_PASSWORD") or env.get("ELASTIC_PASSWORD")
        sinks.append(BulkSink(args.es, targets, user=args.user, password=password,
                              batch_size=200 if live else args.batch, insecure=args.insecure))
    if args.out or not sinks:
        out = args.out or default_out()
        sinks.append(FileSink(out, max_bytes=int(args.max_mb * 1024 * 1024), backups=args.backups))
    return sinks


def emit(sinks, events, markers):
    for stream, ev in events:
        for sink in sinks:
            sink.write(stream, ev)
    for m in markers:
        for sink in sinks:
            sink.marker(m)
        log(f"[{m['ts']:%H:%M:%S}] {m['message']}")


def parse_scenario_spec(spec):
    """name[:offset[:dauer[:key=value,...]]] - z. B. brute-force:2m:5m:src_ip=203.0.113.7"""
    parts = spec.split(":", 3)
    name = parts[0]
    offset = parse_duration(parts[1]) if len(parts) > 1 and parts[1] else 0.0
    duration = parse_duration(parts[2]) if len(parts) > 2 and parts[2] else 300.0
    params = parse_params([parts[3]]) if len(parts) > 3 else {}
    if name not in SCENARIOS:
        raise SystemExit(f"Unbekanntes Szenario {name!r}. Verfügbar: {', '.join(sorted(SCENARIOS))}")
    return name, offset, duration, params


def add_cli_scenarios(engine, specs, ref):
    for spec in specs or []:
        name, offset, duration, params = parse_scenario_spec(spec)
        start = ref + timedelta(seconds=offset)
        sc = create(name, engine.world, engine.rng, start, start + timedelta(seconds=duration), params)
        engine.add_scenario(sc)
        log(f"Szenario geplant: {sc.name} {sc.describe()} von {start:%Y-%m-%d %H:%M:%S} "
            f"für {duration:.0f}s (UTC)")


# --- Steuerdatei für laufende live-Generatoren ---------------------------------------------

def control_path(out):
    return os.path.join(out, CONTROL_FILE)


def read_control(out):
    try:
        with open(control_path(out), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"scenarios": []}


def write_control(out, data):
    os.makedirs(out, exist_ok=True)
    tmp = control_path(out) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, control_path(out))


class ControlWatcher:
    def __init__(self, engine, out):
        self.engine = engine
        self.out = out
        self.mtime = None
        self.ids = set()

    def poll(self, now):
        try:
            mtime = os.stat(control_path(self.out)).st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime == self.mtime:
            return
        self.mtime = mtime
        wanted = {}
        for entry in read_control(self.out).get("scenarios", []):
            end = parse_time(entry["end"])
            if end > now:
                wanted[entry["id"]] = entry
        for sid in list(self.ids - set(wanted)):
            self.engine.remove_scenario(sid, now)
            self.ids.discard(sid)
            log(f"Szenario {sid} entfernt")
        for sid, entry in wanted.items():
            if sid in self.ids:
                continue
            sc = create(entry["name"], self.engine.world, self.engine.rng, parse_time(entry["start"]),
                        parse_time(entry["end"]), entry.get("params"), sid=sid)
            self.engine.add_scenario(sc)
            self.ids.add(sid)
            log(f"Szenario übernommen: {sc.name} {sc.describe()} bis {sc.end:%H:%M:%S} UTC")


# --- Kommandos ---------------------------------------------------------------------------

def cmd_live(args):
    profile = load_profile(args.profile)
    rate = args.rate or profile.get("rate", 10)
    if args.no_diurnal:
        profile["diurnal"] = False
    engine = Engine(profile, seed=args.seed)
    sinks = build_sinks(args, profile, live=True)
    out = args.out or default_out()
    os.makedirs(out, exist_ok=True)
    watcher = ControlWatcher(engine, out)
    started = now_utc()
    add_cli_scenarios(engine, args.scenario, started)
    targets = ", ".join(type(s).__name__ for s in sinks)
    log(f"loggen live: Profil={args.profile}, Rate={rate}/s, Ausgabe={targets}, Verzeichnis={out}")
    log("Szenarien aus einem zweiten Terminal: python loggen.py scenario <name>  (Strg+C beendet)")

    t_prev = started
    last_status = last_beat = time.monotonic()
    total = 0
    try:
        while True:
            time.sleep(args.tick)
            now = now_utc()
            watcher.poll(now)
            dt = (now - t_prev).total_seconds()
            events = engine.tick(t_prev, dt, rate)
            emit(sinks, events, engine.pop_markers())
            for sink in sinks:
                sink.flush()
            total += len(events)
            t_prev = now
            mono = time.monotonic()
            if mono - last_beat > 5:
                with open(os.path.join(out, HEARTBEAT_FILE), "w") as fh:
                    fh.write(now.isoformat())
                last_beat = mono
            if mono - last_status > 30:
                active = [sc.name for sc in engine.scenarios.values() if sc.state == "active"]
                log(f"[{now:%H:%M:%S}] {total:,} Ereignisse, aktive Szenarien: {', '.join(active) or '-'}")
                last_status = mono
            if args.duration and (now - started).total_seconds() >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        for sink in sinks:
            sink.close()
            if isinstance(sink, BulkSink):
                log(sink.report())
        log(f"Beendet nach {total:,} Ereignissen.")


def cmd_backfill(args):
    profile = load_profile(args.profile)
    if args.no_diurnal:
        profile["diurnal"] = False
    ref = now_utc()
    end = parse_time(args.to, ref)
    start = parse_time(args.from_, ref)
    span = (end - start).total_seconds()
    if span <= 0:
        raise SystemExit("--from muss vor --to liegen")
    engine = Engine(profile, seed=args.seed)
    if args.events:
        samples = [start + timedelta(seconds=span * i / 500) for i in range(500)]
        mean = sum(diurnal(t) for t in samples) / len(samples) if engine.use_diurnal else 1.0
        rate = args.events / span / mean
    else:
        rate = args.rate or profile.get("rate", 10)
    sinks = build_sinks(args, profile, live=False)
    add_cli_scenarios(engine, args.scenario, start)
    tick = max(1.0, span / 100000)
    log(f"loggen backfill: Profil={args.profile}, {start:%Y-%m-%d %H:%M} bis {end:%Y-%m-%d %H:%M} UTC, "
        f"Seed={args.seed}, Ziel={args.events or 'Rate %.1f/s' % rate} Ereignisse")

    count, t = 0, start
    started, last = time.monotonic(), time.monotonic()
    step = timedelta(seconds=tick)
    try:
        while t < end and (not args.events or count < args.events):
            events = engine.tick(t, min(tick, (end - t).total_seconds()), rate)
            if args.events:
                events = events[: args.events - count]
            emit(sinks, events, engine.pop_markers())
            count += len(events)
            t += step
            if not args.stdout and time.monotonic() - last > 3:
                pct = 100 * (t - start).total_seconds() / span
                log(f"  {count:>12,} Ereignisse  {pct:5.1f} %  "
                    f"({count / (time.monotonic() - started):,.0f}/s)")
                last = time.monotonic()
        emit(sinks, [], engine.pop_markers())
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        for sink in sinks:
            try:
                sink.close()
            except BrokenPipeError:
                pass
            if isinstance(sink, BulkSink):
                log(sink.report())
    log(f"Fertig: {count:,} Ereignisse in {time.monotonic() - started:.1f}s.")


def cmd_scenario(args):
    out = args.out or default_out()
    if args.list or not (args.name or args.stop or args.status):
        log("Verfügbare Szenarien:\n")
        for name, cls in sorted(SCENARIOS.items()):
            defaults = ", ".join(f"{k}={v}" for k, v in cls.defaults.items()) or "-"
            log(f"  {name}\n      {cls.description}\n      Parameter: {defaults}\n      Alert-Idee: {cls.alert_hint}\n")
        return

    data = read_control(out)
    now = now_utc()
    data["scenarios"] = [e for e in data.get("scenarios", []) if parse_time(e["end"]) > now]

    if args.stop:
        before = len(data["scenarios"])
        if args.stop != "all":
            data["scenarios"] = [e for e in data["scenarios"] if e["name"] != args.stop and e["id"] != args.stop]
        else:
            data["scenarios"] = []
        write_control(out, data)
        log(f"{before - len(data['scenarios'])} Szenario(s) gestoppt.")
        return

    if args.status:
        if not data["scenarios"]:
            log("Keine aktiven oder geplanten Szenarien.")
        for e in data["scenarios"]:
            state = "aktiv" if parse_time(e["start"]) <= now else "geplant"
            log(f"  {e['id']}: {e['name']} {state} bis {parse_time(e['end']):%H:%M:%S} UTC  {fmt_params(e.get('params'))}")
        _check_heartbeat(out, now)
        return

    if args.name not in SCENARIOS:
        raise SystemExit(f"Unbekanntes Szenario {args.name!r}. Verfügbar: {', '.join(sorted(SCENARIOS))}")
    start = now + timedelta(seconds=args.delay)
    end = start + timedelta(seconds=args.duration)
    entry = {"id": f"{args.name}-{start:%H%M%S}", "name": args.name, "start": start.isoformat(),
             "end": end.isoformat(), "params": parse_params(args.param)}
    data["scenarios"].append(entry)
    write_control(out, data)
    log(f"Szenario {args.name} eingeplant: {start:%H:%M:%S} bis {end:%H:%M:%S} UTC  {fmt_params(entry['params'])}")
    _check_heartbeat(out, now)


def _check_heartbeat(out, now):
    try:
        age = time.time() - os.stat(os.path.join(out, HEARTBEAT_FILE)).st_mtime
    except FileNotFoundError:
        age = None
    if age is None or age > 15:
        log(f"Hinweis: Kein laufender live-Generator für {out} gefunden. Das Szenario wird aktiv, "
            "sobald 'loggen.py live' mit demselben Ausgabeverzeichnis läuft.")


def cmd_profiles(args):
    for f in sorted(os.listdir(PROFILE_DIR)):
        if f.endswith(".json"):
            with open(os.path.join(PROFILE_DIR, f), encoding="utf-8") as fh:
                p = json.load(fh)
            log(f"  {f[:-5]:<16} {p.get('description', '')}")
            for s in p.get("streams", []):
                log(f"      {s['name']:<12} kind={s['kind']:<9} format={s['format']:<11} -> {s['file']}")


def cmd_formats(args):
    for f in FORMATS.values():
        log(f"  {f.name:<11} kinds={','.join(f.kinds):<36} {f.description}")


def add_output_args(p):
    g = p.add_argument_group("Ausgabe")
    g.add_argument("--out", help="Ausgabeverzeichnis (Standard: $LOGGEN_OUT oder ../data/generated)")
    g.add_argument("--stdout", action="store_true", help="auf stdout schreiben")
    g.add_argument("--show-stream", action="store_true", help="bei --stdout den Stream-Namen voranstellen")
    g.add_argument("--max-mb", type=float, default=50, help="Rotation ab dieser Dateigröße (MB, 0 = aus)")
    g.add_argument("--backups", type=int, default=3, help="Anzahl rotierter Dateien")
    g.add_argument("--es", help="Elasticsearch-URL für direkten Bulk-Import (ECS-JSON)")
    g.add_argument("--targets", help="kommagetrennte Ziel-Data-Streams/Indizes für --es")
    g.add_argument("--user", default=os.environ.get("ELASTIC_USER", "elastic"))
    g.add_argument("--password", help="Standard: $ELASTIC_PASSWORD oder Wert aus ../.env")
    g.add_argument("--batch", type=int, default=5000, help="Dokumente pro Bulk-Request")
    g.add_argument("--insecure", action="store_true", help="TLS-Zertifikat nicht prüfen")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="loggen", description="Logdaten-Generator für die Elastic-Stack-Schulung",
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"loggen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("live", help="kontinuierlich Logs mit aktuellem Zeitstempel erzeugen")
    p.add_argument("--profile", default=os.environ.get("LOGGEN_PROFILE", "alerting"))
    p.add_argument("--rate", type=float, default=float(os.environ.get("LOGGEN_RATE", 0)) or None,
                   help="Ereignisse pro Sekunde (Mittelwert, Standard aus Profil)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--scenario", action="append", metavar="NAME[:OFFSET[:DAUER[:k=v,...]]]",
                   help="Szenario relativ zum Start einplanen, mehrfach möglich")
    p.add_argument("--duration", type=parse_duration, default=0, help="nach dieser Dauer beenden (z. B. 10m)")
    p.add_argument("--tick", type=float, default=0.25, help=argparse.SUPPRESS)
    p.add_argument("--no-diurnal", action="store_true", help="keinen Tagesgang simulieren")
    add_output_args(p)
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("backfill", help="historischen Zeitraum so schnell wie möglich erzeugen")
    p.add_argument("--profile", default="alerting")
    p.add_argument("--from", dest="from_", default="now-1d", help="Start (now-7d, ISO-Zeit)")
    p.add_argument("--to", default="now", help="Ende (now, ISO-Zeit)")
    p.add_argument("--events", type=int, help="Gesamtzahl Ereignisse (sonst Rate aus Profil)")
    p.add_argument("--rate", type=float, help="Ereignisse pro Sekunde Ereigniszeit")
    p.add_argument("--seed", type=int, default=42, help="Seed für reproduzierbare Daten (Standard 42)")
    p.add_argument("--scenario", action="append", metavar="NAME[:OFFSET[:DAUER[:k=v,...]]]",
                   help="Szenario relativ zu --from einplanen, mehrfach möglich")
    p.add_argument("--no-diurnal", action="store_true")
    add_output_args(p)
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("scenario", help="Szenario in einen laufenden live-Generator einspielen")
    p.add_argument("name", nargs="?", help="Name des Szenarios (ohne Angabe: Liste)")
    p.add_argument("--duration", type=parse_duration, default=300, help="Dauer (Standard 5m)")
    p.add_argument("--delay", type=parse_duration, default=0, help="Startverzögerung (z. B. 1m)")
    p.add_argument("--param", action="append", metavar="key=value", help="Szenario-Parameter, mehrfach möglich")
    p.add_argument("--list", action="store_true", help="verfügbare Szenarien anzeigen")
    p.add_argument("--status", action="store_true", help="aktive und geplante Szenarien anzeigen")
    p.add_argument("--stop", metavar="NAME|ID|all", help="Szenario vorzeitig beenden")
    p.add_argument("--out", help="Ausgabeverzeichnis des live-Generators")
    p.set_defaults(func=cmd_scenario)

    p = sub.add_parser("profiles", help="verfügbare Profile anzeigen")
    p.set_defaults(func=cmd_profiles)
    p = sub.add_parser("formats", help="verfügbare Formate anzeigen")
    p.set_defaults(func=cmd_formats)

    args = parser.parse_args(argv)
    args.func(args)
