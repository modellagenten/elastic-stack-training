"""Zeitgesteuerte Erzeugung: Basisereignisse nach Rate und Tagesgang, Szenarien einmischen."""

import random
from datetime import timedelta

from .model import EventFactory, World, _cum, diurnal
from .formats import FORMATS


class Engine:
    def __init__(self, profile, seed=None):
        self.profile = profile
        self.rng = random.Random(seed)
        self.world = World(profile, self.rng)
        self.factory = EventFactory(self.world, self.rng, profile)
        self.streams = profile["streams"]
        self.stream_cw = _cum([s.get("weight", 1) for s in self.streams])
        self.use_diurnal = profile.get("diurnal", True)
        self.scenarios = {}
        self.markers = []
        self._carry = 0.0
        self._extra_carry = {}
        self._fallback = {}
        for stream in self.streams:
            self._fallback.setdefault(stream["kind"], stream)
        ecs_streams = [s for s in self.streams if s["format"] == "ecs_json"]
        self._any = ecs_streams[0] if ecs_streams else None

    def stream_for(self, kind):
        stream = self._fallback.get(kind)
        if stream is None:
            stream = self._any or {"name": kind, "kind": kind, "format": "ecs_json", "file": f"{kind}.ecs.json"}
            self._fallback[kind] = stream
        return stream

    def add_scenario(self, scenario):
        self.scenarios[scenario.id] = scenario

    def remove_scenario(self, scenario_id, now):
        sc = self.scenarios.pop(scenario_id, None)
        if sc and sc.state == "active":
            self._marker(sc, "end", now)

    def _marker(self, sc, action, ts):
        sc.state = "active" if action == "start" else "done"
        self.markers.append({
            "ts": ts, "kind": "marker", "scenario": sc.name, "action": action, "params": sc.params,
            "start": sc.start, "end": sc.end,
            "message": f"Szenario {sc.name} {'gestartet' if action == 'start' else 'beendet'} {sc.describe()}",
        })

    def pop_markers(self):
        out, self.markers = self.markers, []
        return out

    def _active(self, ts):
        return [sc for sc in self.scenarios.values() if sc.start <= ts < sc.end]

    def tick(self, t0, dt, rate):
        """Erzeugt alle Ereignisse im Intervall [t0, t0+dt), sortiert nach Zeitstempel."""
        rng, factory = self.rng, self.factory
        t1 = t0 + timedelta(seconds=dt)

        for sc in self.scenarios.values():
            if sc.state == "pending" and sc.start < t1:
                self._marker(sc, "start", max(sc.start, t0))
            elif sc.state == "active" and sc.end <= t0:
                self._marker(sc, "end", sc.end)

        expected = rate * dt * (diurnal(t0) if self.use_diurnal else 1.0) + self._carry
        n = int(expected)
        self._carry = expected - n
        active = self._active(t0) or self._active(t1 - timedelta(microseconds=1))

        out = []
        for _ in range(n):
            ts = t0 + timedelta(seconds=rng.random() * dt)
            stream = rng.choices(self.streams, cum_weights=self.stream_cw)[0]
            ev = factory.make(stream["kind"], ts)
            for sc in active:
                if ev is not None and sc.start <= ts < sc.end:
                    ev = sc.mutate(ev, factory)
            if ev is not None:
                out.append((stream, ev))

        for sc in active:
            if not sc.extra_rate:
                continue
            exp = sc.extra_rate * dt + self._extra_carry.get(sc.id, 0.0)
            k = int(exp)
            self._extra_carry[sc.id] = exp - k
            for _ in range(k):
                ts = t0 + timedelta(seconds=rng.random() * dt)
                if not sc.start <= ts < sc.end:
                    continue
                for ev in sc.extra(factory, ts):
                    ev["scenario"] = sc.name
                    out.append((self.stream_for(ev["kind"]), ev))

        out.sort(key=lambda pair: pair[1]["ts"])
        for _, ev in out:
            factory.decorate(ev)
        return out


def validate_profile(profile):
    errors = []
    for stream in profile.get("streams", []):
        fmt = FORMATS.get(stream.get("format"))
        if fmt is None:
            errors.append(f"Stream {stream.get('name')}: unbekanntes Format {stream.get('format')!r}")
        elif stream.get("kind") not in fmt.kinds:
            errors.append(f"Stream {stream.get('name')}: Format {fmt.name} unterstützt kind "
                          f"{stream.get('kind')!r} nicht (erlaubt: {', '.join(fmt.kinds)})")
    if not profile.get("streams"):
        errors.append("Profil enthält keine streams")
    return errors
