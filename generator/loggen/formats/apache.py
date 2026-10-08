MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def clf_time(ts):
    return f"{ts.day:02d}/{MONTHS[ts.month - 1]}/{ts.year}:{ts:%H:%M:%S} +0000"


def render(ev):
    size = ev["bytes"] if ev["bytes"] else "-"
    return (f'{ev["client_ip"]} - {ev["user"]} [{clf_time(ev["ts"])}] '
            f'"{ev["method"]} {ev["path"]} HTTP/1.1" {ev["status"]} {size} '
            f'"{ev["referrer"]}" "{ev["user_agent"]}"')
