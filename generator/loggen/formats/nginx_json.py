import json


def render(ev):
    doc = {
        "time_iso8601": ev["ts"].strftime("%Y-%m-%dT%H:%M:%S.") + f"{ev['ts'].microsecond // 1000:03d}+00:00",
        "remote_addr": ev["client_ip"],
        "remote_user": ev["user"],
        "host": ev["host"]["name"],
        "upstream": ev["service"]["name"],
        "request_method": ev["method"],
        "request_uri": ev["path"],
        "status": ev["status"],
        "body_bytes_sent": ev["bytes"],
        "request_time": round(ev["duration_ms"] / 1000.0, 3),
        "http_referer": ev["referrer"],
        "http_user_agent": ev["user_agent"],
        "trace_id": ev["trace_id"],
    }
    if ev.get("scenario"):
        doc["scenario"] = ev["scenario"]
    return json.dumps(doc, ensure_ascii=False)
