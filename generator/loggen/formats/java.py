def _short_logger(name):
    parts = name.split(".")
    return ".".join(p[0] for p in parts[:-1]) + "." + parts[-1] if len(parts) > 1 else name


def render(ev):
    ts = ev["ts"]
    stamp = ts.strftime("%Y-%m-%d %H:%M:%S,") + f"{ts.microsecond // 1000:03d}"
    line = (f"{stamp} {ev['log_level']:<5} [{ev['thread']}] {_short_logger(ev['logger'])} "
            f"[trace.id={ev['trace_id']}] - {ev['message']}")
    exc = ev.get("exception")
    if not exc:
        return line
    cls, msg, frames = exc
    lines = [line, f"{cls}: {msg}"]
    lines += [f"\tat {frame}" for frame in frames]
    lines.append(f"\t... {len(frames) + 38} more")
    return "\n".join(lines)
