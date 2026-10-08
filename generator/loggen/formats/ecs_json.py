"""Abbildung eines Ereignisses auf ECS-Felder (https://www.elastic.co/docs/reference/ecs)."""

import json

CATEGORY = {"http": ["web"], "auth": ["authentication"], "syslog": ["host"], "app": ["process"],
            "firewall": ["network"]}


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def to_ecs(ev):
    kind = ev["kind"]
    host = ev["host"]
    doc = {
        "@timestamp": iso(ev["ts"]),
        "message": ev["message"],
        "event": {"id": ev["id"], "kind": "event", "category": CATEGORY[kind], "dataset": f"loggen.{kind}"},
        "host": {"name": host["name"], "ip": host["ip"], "os": {"type": "linux"}},
        "log": {"level": ev["level"]},
    }
    if ev.get("service"):
        doc["service"] = {"name": ev["service"]["name"], "environment": "prod"}

    if kind == "http":
        status = ev["status"]
        doc["event"].update(outcome="success" if status < 400 else "failure",
                            duration=int(ev["duration_ms"] * 1_000_000))
        doc["source"] = {"ip": ev["client_ip"], "geo": {"country_iso_code": ev["country"]}}
        doc["http"] = {"request": {"method": ev["method"]},
                       "response": {"status_code": status, "body": {"bytes": ev["bytes"]}}}
        doc["url"] = {"path": ev["path"].split("?")[0], "original": ev["path"]}
        doc["user_agent"] = {"original": ev["user_agent"]}
        if ev["user"] != "-":
            doc["user"] = {"name": ev["user"]}
        doc["trace"] = {"id": ev["trace_id"]}
        doc["span"] = {"id": ev["span_id"]}
    elif kind == "auth":
        doc["event"].update(outcome=ev["outcome"], action=ev["action"])
        doc["process"] = {"name": ev["program"], "pid": ev["pid"]}
        doc["user"] = {"name": ev["user"]}
        if ev.get("src_ip"):
            doc["source"] = {"ip": ev["src_ip"]}
    elif kind == "syslog":
        doc["process"] = {"name": ev["program"]}
        if ev.get("pid"):
            doc["process"]["pid"] = ev["pid"]
        doc["log"]["syslog"] = {"severity": {"name": ev["severity"]}}
    elif kind == "app":
        doc["log"]["logger"] = ev["logger"]
        doc["process"] = {"name": "java", "thread": {"name": ev["thread"]}}
        doc["trace"] = {"id": ev["trace_id"]}
        doc["span"] = {"id": ev["span_id"]}
        if ev.get("exception"):
            cls, msg, frames = ev["exception"]
            doc["error"] = {"type": cls, "message": msg,
                            "stack_trace": "\n".join([f"{cls}: {msg}"] + [f"\tat {f}" for f in frames])}
    elif kind == "firewall":
        doc["event"].update(action=ev["action"], outcome="failure" if ev["action"] == "deny" else "success")
        doc["source"] = {"ip": ev["src_ip"], "port": ev["src_port"], "bytes": ev["sent_bytes"]}
        doc["destination"] = {"ip": ev["dst_ip"], "port": ev["dst_port"], "bytes": ev["rcvd_bytes"]}
        doc["network"] = {"transport": ev["proto"], "direction": ev["direction"],
                          "protocol": ev["fw_service"].lower()}
        doc["rule"] = {"id": str(ev["rule_id"])}

    labels = dict(ev.get("labels") or {})
    if ev.get("scenario"):
        labels["scenario"] = ev["scenario"]
    if labels:
        doc["labels"] = labels
    if ev.get("tags"):
        doc["tags"] = ev["tags"]
    if ev.get("links"):
        doc["links"] = ev["links"]
    return doc


def marker_to_ecs(m):
    return {
        "@timestamp": iso(m["ts"]),
        "message": m["message"],
        "event": {"kind": "event", "category": ["configuration"], "action": f"scenario-{m['action']}",
                  "dataset": "loggen.scenario", "start": iso(m["start"]), "end": iso(m["end"])},
        "labels": {"scenario": m["scenario"], **{f"param_{k}": str(v) for k, v in m["params"].items()}},
        "host": {"name": "loggen"},
    }


def render(ev):
    return json.dumps(to_ecs(ev), ensure_ascii=False)
