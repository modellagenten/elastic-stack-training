"""Ausgabeziele: Dateien (mit Rotation), stdout und Elasticsearch-Bulk-API."""

import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

from .formats import FORMATS
from .formats.ecs_json import marker_to_ecs, to_ecs

MARKER_FILE = "loggen-scenarios.log"


class FileSink:
    def __init__(self, out_dir, max_bytes=50 * 1024 * 1024, backups=3):
        self.out_dir = out_dir
        self.max_bytes = max_bytes
        self.backups = backups
        self.handles = {}
        os.makedirs(out_dir, exist_ok=True)

    def _open(self, filename, header=None):
        path = os.path.join(self.out_dir, filename)
        fh = open(path, "a", encoding="utf-8")
        if header and fh.tell() == 0:
            fh.write(header + "\n")
        self.handles[filename] = (fh, header)
        return fh

    def _rotate(self, filename):
        fh, header = self.handles.pop(filename)
        fh.close()
        base = os.path.join(self.out_dir, filename)
        for i in range(self.backups, 0, -1):
            src = base if i == 1 else f"{base}.{i - 1}"
            if os.path.exists(src):
                os.replace(src, f"{base}.{i}")
        return self._open(filename, header)

    def _write(self, filename, text, header=None):
        entry = self.handles.get(filename)
        fh = entry[0] if entry else self._open(filename, header)
        fh.write(text + "\n")
        if self.max_bytes and fh.tell() > self.max_bytes:
            self._rotate(filename)

    def write(self, stream, ev):
        fmt = FORMATS[stream["format"]]
        self._write(stream["file"], fmt.render(ev), fmt.header)

    def marker(self, m):
        self._write(MARKER_FILE, json.dumps(marker_to_ecs(m), ensure_ascii=False))

    def flush(self):
        for fh, _ in self.handles.values():
            fh.flush()

    def close(self):
        for fh, _ in self.handles.values():
            fh.close()
        self.handles = {}


class StdoutSink:
    def __init__(self, with_stream_name=False):
        self.with_stream_name = with_stream_name

    def write(self, stream, ev):
        text = FORMATS[stream["format"]].render(ev)
        if self.with_stream_name:
            text = f"[{stream['name']}] {text}"
        sys.stdout.write(text + "\n")

    def marker(self, m):
        sys.stdout.write(json.dumps(marker_to_ecs(m), ensure_ascii=False) + "\n")

    def flush(self):
        sys.stdout.flush()

    def close(self):
        self.flush()


class BulkSink:
    """Schreibt ECS-Dokumente per _bulk in ein oder mehrere Ziele (Data Streams oder Indizes).

    Jedes Ziel bekommt exakt dieselben Dokumente; die Zeit pro Ziel wird gemessen.
    """

    def __init__(self, url, targets, user=None, password=None, batch_size=5000, insecure=False):
        self.url = url.rstrip("/")
        self.targets = targets
        self.batch_size = batch_size
        self.buffer = []
        self.headers = {"Content-Type": "application/x-ndjson"}
        if user:
            token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"
        self.ctx = ssl._create_unverified_context() if insecure else None
        self.stats = {t: {"docs": 0, "errors": 0, "seconds": 0.0} for t in targets}
        self.first_errors = []

    def write(self, stream, ev):
        self.buffer.append(json.dumps(to_ecs(ev), ensure_ascii=False))
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def marker(self, m):
        pass

    def _post(self, target, body):
        req = urllib.request.Request(f"{self.url}/{target}/_bulk?filter_path=errors,items.*.error",
                                     data=body, headers=self.headers, method="POST")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Bulk nach {target} fehlgeschlagen: HTTP {exc.code} {exc.read()[:500]!r}")
            except urllib.error.URLError as exc:
                if attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Elasticsearch unter {self.url} nicht erreichbar: {exc.reason}")

    def flush(self):
        if not self.buffer:
            return
        body = ("".join('{"create":{}}\n' + doc + "\n" for doc in self.buffer)).encode("utf-8")
        for target in self.targets:
            start = time.perf_counter()
            result = self._post(target, body)
            st = self.stats[target]
            st["seconds"] += time.perf_counter() - start
            st["docs"] += len(self.buffer)
            if result.get("errors"):
                errs = [item for item in result.get("items", []) if any("error" in v for v in item.values())]
                st["errors"] += len(errs)
                st["docs"] -= len(errs)
                if len(self.first_errors) < 3 and errs:
                    self.first_errors.append((target, errs[0]))
        self.buffer = []

    def close(self):
        self.flush()

    def report(self):
        lines = ["", "Bulk-Statistik pro Ziel:",
                 f"  {'Ziel':<40} {'Dokumente':>12} {'Fehler':>8} {'Sekunden':>10} {'Docs/s':>10}"]
        for target, st in self.stats.items():
            rate = st["docs"] / st["seconds"] if st["seconds"] else 0
            lines.append(f"  {target:<40} {st['docs']:>12,} {st['errors']:>8,} {st['seconds']:>10.1f} {rate:>10,.0f}")
        for target, err in self.first_errors:
            lines.append(f"  Beispielfehler in {target}: {json.dumps(err)[:400]}")
        return "\n".join(lines)
