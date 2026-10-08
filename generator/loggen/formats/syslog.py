from .apache import MONTHS

SEVERITY = {"emerg": 0, "alert": 1, "crit": 2, "err": 3, "warning": 4, "notice": 5, "info": 6, "debug": 7}
# auth/authpriv = 10, daemon = 3, kern = 0, cron = 9
FACILITY = {"kernel": 0, "CRON": 9, "sshd": 10, "sudo": 10}


def _severity(ev):
    if ev["kind"] == "auth":
        return "warning" if ev.get("outcome") == "failure" else "info"
    return ev.get("severity", "info")


def _tag(ev):
    return f"{ev['program']}[{ev['pid']}]" if ev.get("pid") else ev["program"]


def render_3164(ev):
    ts = ev["ts"]
    return f"{MONTHS[ts.month - 1]} {ts.day:2d} {ts:%H:%M:%S} {ev['host']['name']} {_tag(ev)}: {ev['message']}"


def render_5424(ev):
    ts = ev["ts"]
    pri = FACILITY.get(ev["program"], 3) * 8 + SEVERITY.get(_severity(ev), 6)
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    sd = f'[loggen@32473 scenario="{ev["scenario"]}"]' if ev.get("scenario") else "-"
    return f"<{pri}>1 {stamp} {ev['host']['name']} {ev['program']} {ev.get('pid') or '-'} - {sd} {ev['message']}"
