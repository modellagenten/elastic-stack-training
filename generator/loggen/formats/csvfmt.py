import csv
import io

HEADER = "timestamp,host,service,client_ip,method,path,status,bytes,duration_ms,user_agent"


def render(ev):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow([
        ev["ts"].strftime("%Y-%m-%dT%H:%M:%S.") + f"{ev['ts'].microsecond // 1000:03d}Z",
        ev["host"]["name"], ev["service"]["name"], ev["client_ip"], ev["method"], ev["path"],
        ev["status"], ev["bytes"], ev["duration_ms"], ev["user_agent"],
    ])
    return buf.getvalue()
