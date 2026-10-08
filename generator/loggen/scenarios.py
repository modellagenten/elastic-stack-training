"""Störungsszenarien für Alerting-Übungen.

Ein Szenario ist zwischen ``start`` und ``end`` aktiv. Es kann Basisereignisse verändern
(``mutate``) oder zusätzliche Ereignisse mit ``rate`` pro Sekunde erzeugen (``extra``).
Betroffene Ereignisse tragen ``scenario=<name>`` (in JSON-Formaten als ``labels.scenario``).
"""

SCENARIOS = {}


def register(cls):
    SCENARIOS[cls.name] = cls
    return cls


def _coerce(value, default):
    if isinstance(default, bool):
        return str(value).lower() in ("1", "true", "yes", "ja")
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


class Scenario:
    name = ""
    description = ""
    alert_hint = ""
    defaults = {}

    def __init__(self, world, rng, start, end, params=None, sid=None):
        self.world = world
        self.rng = rng
        self.start = start
        self.end = end
        merged = dict(self.defaults)
        for key, value in (params or {}).items():
            merged[key] = _coerce(value, self.defaults[key]) if key in self.defaults else value
        self.params = merged
        self.id = sid or f"{self.name}-{start:%Y%m%d%H%M%S}"
        self.state = "pending"
        self.extra_rate = float(self.params.get("rate", 0) or 0)
        self.setup()

    def setup(self):
        pass

    def _host(self, role):
        name = self.params.get("host", "auto")
        if name != "auto" and name in self.world.host_by_name:
            return self.world.host_by_name[name]
        hosts = self.world.hosts_of(role)
        return hosts[min(1, len(hosts) - 1)]

    def _service(self, pool):
        name = self.params.get("service", "auto")
        svc = self.world.service_by_name.get(name)
        return svc or pool[min(1, len(pool) - 1)]

    def progress(self, ts):
        total = (self.end - self.start).total_seconds() or 1
        return min(1.0, max(0.0, (ts - self.start).total_seconds() / total))

    def mutate(self, ev, factory):
        return ev

    def extra(self, factory, ts):
        return []

    def describe(self):
        return "(" + ", ".join(f"{k}={v}" for k, v in sorted(self.params.items())) + ")"


@register
class ErrorSpike(Scenario):
    name = "error-spike"
    description = "Anteil der HTTP-5xx-Antworten und ERROR-Logs eines Services steigt stark an"
    alert_hint = "Threshold-/ES|QL-Rule: Anteil http.response.status_code >= 500 pro service.name"
    defaults = {"service": "checkout", "error_rate": 0.3, "app_service": "payment-service"}

    def setup(self):
        self.svc = self._service(self.world.web_services)
        self.app_svc = self.world.service_by_name.get(self.params["app_service"]) or self.world.app_services[0]
        self.params["service"] = self.svc["name"]

    def mutate(self, ev, factory):
        rate = self.params["error_rate"]
        if ev["kind"] == "http" and ev["service"] is self.svc and self.rng.random() < rate:
            status = self.rng.choice([500, 502, 503, 504])
            ev.update(status=status, bytes=self.rng.randint(150, 600), level="error", scenario=self.name,
                      message=f"{ev['method']} {ev['path']} HTTP/1.1 {status}")
            if status == 504:
                ev["duration_ms"] = round(30000 + self.rng.random() * 100, 3)
        elif ev["kind"] == "app" and ev["service"] is self.app_svc and self.rng.random() < rate:
            return factory.make_app(ev["ts"], service=self.app_svc, level="ERROR",
                                    message="Payment provider returned an error for order "
                                            f"{self.rng.randint(100000, 999999)}") | {"scenario": self.name}
        return ev


@register
class BruteForce(Scenario):
    name = "brute-force"
    description = "SSH-Brute-Force: viele fehlgeschlagene Logins von einer externen IP, am Ende ein erfolgreicher Login"
    alert_hint = "Query-Rule auf auth-Logs: event.outcome:failure, gruppiert nach source.ip, > 20 in 5 Min."
    defaults = {"host": "auto", "src_ip": "auto", "rate": 4.0, "success_at_end": True}

    def setup(self):
        self.host = self._host("web")
        if self.params["src_ip"] == "auto":
            self.params["src_ip"] = self.world.random_public_ip()
        self.params["host"] = self.host["name"]
        self.succeeded = False

    def extra(self, factory, ts):
        rng = self.rng
        ev = factory.make_auth(ts, host=self.host)
        ip = self.params["src_ip"]
        port = rng.randint(30000, 65000)
        if self.params["success_at_end"] and not self.succeeded and self.progress(ts) > 0.95:
            self.succeeded = True
            ev.update(program="sshd", user="deploy", src_ip=ip, outcome="success", action="ssh_login", level="info",
                      message=f"Accepted password for deploy from {ip} port {port} ssh2")
            return [ev]
        if rng.random() < 0.6:
            user = rng.choice(["admin", "test", "oracle", "postgres", "guest", "pi", "ftpuser", "git"])
            msg = f"Failed password for invalid user {user} from {ip} port {port} ssh2"
        else:
            user = rng.choice(["root", "deploy", "ubuntu"])
            msg = f"Failed password for {user} from {ip} port {port} ssh2"
        ev.update(program="sshd", user=user, src_ip=ip, outcome="failure", action="ssh_login", level="warn",
                  message=msg)
        return [ev]


@register
class LatencyDegradation(Scenario):
    name = "latency-degradation"
    description = "Antwortzeiten eines Services steigen langsam bis zum Faktor max_factor an"
    alert_hint = "Custom-Threshold-Rule: avg(event.duration) pro service.name, oder Anomaly Detection"
    defaults = {"service": "search", "max_factor": 8.0}

    def setup(self):
        self.svc = self._service(self.world.web_services)
        self.params["service"] = self.svc["name"]

    def mutate(self, ev, factory):
        if ev["kind"] == "http" and ev["service"] is self.svc:
            factor = 1.0 + (self.params["max_factor"] - 1.0) * self.progress(ev["ts"])
            ev["duration_ms"] = round(ev["duration_ms"] * factor, 3)
            ev["scenario"] = self.name
        return ev


@register
class HostSilent(Scenario):
    name = "host-silent"
    description = "Ein Host sendet keine Logs mehr (Ausfall, Agent gestoppt)"
    alert_hint = "Custom-Threshold- oder ES|QL-Rule: count() pro host.name == 0 bzw. Rule 'no data'"
    defaults = {"host": "auto"}

    def setup(self):
        self.host = self._host("app")
        self.params["host"] = self.host["name"]

    def mutate(self, ev, factory):
        return None if ev["host"] is self.host else ev


@register
class DiskFull(Scenario):
    name = "disk-full"
    description = "Datenträger voll: kritische Syslog-Meldungen und Schreibfehler auf einem DB-Host"
    alert_hint = "Query-Rule: log.syslog.severity.name:(crit or err) und message:\"No space left on device\""
    defaults = {"host": "auto", "rate": 0.5}

    def setup(self):
        self.host = self._host("db")
        self.params["host"] = self.host["name"]

    def extra(self, factory, ts):
        rng = self.rng
        choices = [
            ("kernel", "crit", "EXT4-fs warning (device sda1): ext4_dx_add_entry:2516: Directory index full!"),
            ("postgres", "err", f"ERROR:  could not extend file \"base/16384/{rng.randint(10000, 99999)}\": "
                                "No space left on device"),
            ("rsyslogd", "err", "file '/var/log/syslog': write error - No space left on device"),
            ("systemd-journald", "crit", "Failed to write entry, ignoring: No space left on device"),
        ]
        program, severity, msg = rng.choice(choices)
        return [factory.make_syslog(ts, host=self.host, program=program, severity=severity, message=msg)]


@register
class OutOfMemory(Scenario):
    name = "oom"
    description = "OOM-Killer beendet wiederholt den Java-Prozess eines App-Hosts"
    alert_hint = "Query-Rule: message:\"Out of memory\" oder process.name:kernel und log.level:critical"
    defaults = {"host": "auto", "rate": 0.2, "service": "order-service"}

    def setup(self):
        self.host = self._host("app")
        self.params["host"] = self.host["name"]

    def extra(self, factory, ts):
        rng = self.rng
        pid = rng.randint(2000, 9000)
        svc = self.params["service"]
        evs = [factory.make_syslog(ts, host=self.host, program="kernel", severity="crit",
                                   message=f"Out of memory: Killed process {pid} (java) total-vm:{rng.randint(6, 9)}"
                                           f"{rng.randint(100000, 999999)}kB, anon-rss:{rng.randint(3, 4)}"
                                           f"{rng.randint(100000, 999999)}kB, oom_score_adj:0"),
               factory.make_syslog(ts, host=self.host, program="systemd", severity="err",
                                   message=f"{svc}.service: Main process exited, code=killed, status=9/KILL")]
        return evs


@register
class NewUserAgent(Scenario):
    name = "new-user-agent"
    description = "Ein Angreifer scannt die Webseite mit sqlmap (neuer, seltener User-Agent, SQL-Injection-Pfade)"
    alert_hint = "ES|QL-Rule / New-Terms-Logik: bisher unbekannter user_agent.original, oder url.path enthält \"' OR\""
    defaults = {"user_agent": "sqlmap/1.8.9#stable (https://sqlmap.org)", "src_ip": "auto", "rate": 2.0}

    def setup(self):
        if self.params["src_ip"] == "auto":
            self.params["src_ip"] = self.world.random_public_ip()

    def extra(self, factory, ts):
        rng = self.rng
        payload = rng.choice(["1%27%20OR%20%271%27%3D%271", "1%20UNION%20SELECT%20NULL,NULL--",
                              "1%20AND%20SLEEP(5)", "-1%27%20ORDER%20BY%2010--"])
        path = rng.choice(["/products?id=", "/api/v1/orders/", "/search?q="]) + payload
        status = rng.choice([403, 403, 500, 200])
        return [factory.make_http(ts, client_ip=self.params["src_ip"], user_agent=self.params["user_agent"],
                                  path=path, status=status)]


@register
class RareProcess(Scenario):
    name = "rare-process"
    description = "Ein unbekannter Prozess (Crypto-Miner) taucht in Syslog und auth.log eines Web-Hosts auf"
    alert_hint = "ES|QL-Rule: STATS count() BY process.name mit seltenen Werten, oder process.name:xmrig"
    defaults = {"host": "auto", "process": "xmrig", "rate": 0.3}

    def setup(self):
        self.host = self._host("web")
        self.params["host"] = self.host["name"]

    def extra(self, factory, ts):
        rng = self.rng
        proc = self.params["process"]
        if rng.random() < 0.2:
            ev = factory.make_auth(ts, host=self.host)
            ev.update(program="sudo", user="www-data", src_ip=None, outcome="success", action="sudo", level="warn",
                      message=f"www-data : TTY=unknown ; PWD=/tmp ; USER=root ; COMMAND=/tmp/.x/{proc} -B")
            return [ev]
        msg = rng.choice([f"[{ts:%Y-%m-%d %H:%M:%S}] net use pool stratum+tcp://pool.example.net:3333",
                          f"[{ts:%Y-%m-%d %H:%M:%S}] cpu accepted ({rng.randint(1, 500)}/0) diff 120001",
                          f"[{ts:%Y-%m-%d %H:%M:%S}] speed 10s/60s/15m {rng.randint(800, 1200)}.0 H/s"])
        return [factory.make_syslog(ts, host=self.host, program=proc, severity="info", message=msg)]


def create(name, world, rng, start, end, params=None, sid=None):
    cls = SCENARIOS.get(name)
    if cls is None:
        raise ValueError(f"Unbekanntes Szenario {name!r}. Verfügbar: {', '.join(sorted(SCENARIOS))}")
    return cls(world, rng, start, end, params=params, sid=sid)
