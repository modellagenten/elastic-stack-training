"""Registry der Ausgabeformate. Jeder Renderer liefert für ein Ereignis eine (ggf. mehrzeilige) Zeichenkette."""

from collections import namedtuple

from . import apache, csvfmt, ecs_json, java, kv, nginx_json, syslog

Format = namedtuple("Format", "name kinds render header description")

FORMATS = {
    f.name: f
    for f in [
        Format("apache", ("http",), apache.render, None,
               "Apache/Nginx Combined Log Format (access.log)"),
        Format("nginx_json", ("http",), nginx_json.render, None,
               "Nginx-Access-Log als JSON-Zeile (log_format escape=json)"),
        Format("syslog", ("syslog", "auth"), syslog.render_3164, None,
               "Klassisches Syslog nach RFC 3164 wie in /var/log/syslog"),
        Format("syslog5424", ("syslog", "auth"), syslog.render_5424, None,
               "Syslog nach RFC 5424 mit Structured Data (enthält ggf. scenario)"),
        Format("auth", ("auth",), syslog.render_3164, None,
               "Linux /var/log/auth.log (sshd, sudo, CRON)"),
        Format("java", ("app",), java.render, None,
               "Log4j/Logback-Pattern, ERROR mit mehrzeiligem Stacktrace (Multiline!)"),
        Format("ecs_json", ("http", "auth", "syslog", "app", "firewall"), ecs_json.render, None,
               "ECS-konformes JSON (eine Zeile pro Ereignis), auch für den ES-Bulk-Sink"),
        Format("kv", ("firewall",), kv.render, None,
               "Firewall-Traffic-Log im Key-Value-Stil (FortiGate-ähnlich)"),
        Format("csv", ("http",), csvfmt.render, csvfmt.HEADER,
               "CSV mit Kopfzeile (Zugriffsstatistik)"),
    ]
}
