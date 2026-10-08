"""Ereignismodell: Hosts, Services, Benutzer, IP-Pools und Erzeugung einzelner Ereignisse.

Ein Ereignis ist ein einfaches dict mit gemeinsamen Schlüsseln (ts, kind, host, service,
level, message, ...) und kind-spezifischen Feldern. Die Renderer in ``loggen.formats``
bringen es in das jeweilige Ausgabeformat.
"""

import math
import random
from datetime import timedelta

KINDS = ("http", "auth", "syslog", "app", "firewall")

# (name, role, team, base_latency_ms, paths)
SERVICE_CATALOG = [
    ("frontend", "web", "team-web", 25, ["/", "/index.html", "/products", "/products/{id}", "/cart",
                                          "/static/app.js", "/static/style.css", "/images/{id}.jpg",
                                          "/login", "/logout"]),
    ("checkout", "web", "team-shop", 120, ["/checkout", "/checkout/confirm", "/api/cart", "/api/payment"]),
    ("search", "web", "team-search", 60, ["/search?q={q}", "/api/search?q={q}", "/api/suggest?q={q}"]),
    ("api-gateway", "web", "team-platform", 40, ["/api/v1/orders", "/api/v1/orders/{id}",
                                                  "/api/v1/customers/{id}", "/api/v1/health"]),
    ("order-service", "app", "team-shop", 80, []),
    ("payment-service", "app", "team-payments", 150, []),
    ("inventory-service", "app", "team-shop", 50, []),
    ("user-service", "app", "team-platform", 30, []),
    ("postgres", "db", "team-dba", 5, []),
    ("redis", "db", "team-platform", 1, []),
    ("media", "web", "team-web", 15, ["/media/{id}.mp4", "/media/{id}.png", "/thumbnails/{id}.webp"]),
    ("account", "web", "team-platform", 70, ["/account", "/account/settings", "/account/orders",
                                              "/api/v1/profile"]),
    ("shipping-service", "app", "team-logistics", 90, []),
    ("notification-service", "app", "team-platform", 20, []),
    ("recommendation-service", "app", "team-search", 110, []),
    ("pricing-service", "app", "team-shop", 35, []),
    ("audit-service", "app", "team-security", 25, []),
    ("reporting-service", "app", "team-bi", 400, []),
    ("elasticsearch", "db", "team-search", 12, []),
    ("kafka", "db", "team-platform", 3, []),
]

USERS = ["anna.schmidt", "ben.mueller", "clara.weber", "david.fischer", "eva.wagner", "felix.becker",
         "greta.hoffmann", "hannah.schulz", "ivan.koch", "julia.richter", "ubuntu", "deploy", "backup"]
ADMINS = ["ubuntu", "deploy", "anna.schmidt", "ivan.koch"]
INVALID_USERS = ["admin", "test", "oracle", "postgres", "guest", "user", "pi", "ftpuser", "support", "git"]

SEARCH_TERMS = ["laptop", "kopfhoerer", "monitor", "tastatur", "usb-c+kabel", "drucker", "ssd", "webcam"]

USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", 40),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", 15),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", 10),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", 15),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36", 10),
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", 4),
    ("curl/8.9.1", 3),
    ("kube-probe/1.31", 3),
]

HTTP_STATUS = [(200, 850), (304, 40), (301, 20), (302, 10), (404, 50), (401, 10), (403, 5),
               (500, 5), (502, 2), (503, 3)]
HTTP_METHODS = [("GET", 80), ("POST", 15), ("PUT", 3), ("DELETE", 2)]

LOGGERS = {
    "order-service": ["com.example.order.OrderController", "com.example.order.OrderRepository"],
    "payment-service": ["com.example.payment.PaymentGateway", "com.example.payment.FraudCheck"],
    "inventory-service": ["com.example.inventory.StockService", "com.example.inventory.WarehouseClient"],
    "user-service": ["com.example.user.AuthController", "com.example.user.SessionStore"],
}

APP_INFO = [
    "Order {oid} created for customer {cid} in {ms} ms",
    "Payment authorized for order {oid} amount={amount} EUR",
    "Stock reserved for product {pid} quantity={qty}",
    "User {user} logged in successfully",
    "Cache miss for key product:{pid}",
    "Processed batch of {qty} events in {ms} ms",
    "HTTP GET /internal/health returned 200 in {ms} ms",
]
APP_DEBUG = ["Loaded configuration profile 'prod'", "Connection pool stats: active={qty} idle=8 waiting=0"]
APP_WARN = [
    "Slow query detected: {ms} ms SELECT * FROM orders WHERE customer_id = ?",
    "Retrying request to inventory-service (attempt {qty}/3)",
    "Connection pool usage above 80% (active={qty}, max=50)",
    "Deprecated API version v1 used by client {cid}",
]
APP_ERROR = [
    "Failed to process order {oid}",
    "Payment provider returned an error for order {oid}",
    "Unable to reserve stock for product {pid}",
    "Unhandled exception in request handler",
]
EXCEPTIONS = [
    ("java.net.SocketTimeoutException", "Read timed out",
     ["java.base/sun.nio.ch.NioSocketImpl.timedRead(NioSocketImpl.java:288)",
      "java.base/java.net.Socket$SocketInputStream.read(Socket.java:1099)",
      "org.apache.http.impl.io.SessionInputBufferImpl.fillBuffer(SessionInputBufferImpl.java:153)",
      "com.example.inventory.WarehouseClient.reserve(WarehouseClient.java:87)"]),
    ("java.sql.SQLTransientConnectionException",
     "HikariPool-1 - Connection is not available, request timed out after 30000ms.",
     ["com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)",
      "com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:181)",
      "com.example.order.OrderRepository.save(OrderRepository.java:52)"]),
    ("java.lang.NullPointerException",
     "Cannot invoke \"com.example.order.Customer.getAddress()\" because \"customer\" is null",
     ["com.example.order.OrderController.create(OrderController.java:118)",
      "jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)",
      "org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:885)"]),
    ("java.lang.IllegalStateException", "Payment provider responded with HTTP 502",
     ["com.example.payment.PaymentGateway.authorize(PaymentGateway.java:64)",
      "com.example.payment.PaymentService.pay(PaymentService.java:41)"]),
]

SYSLOG_MESSAGES = [
    ("systemd", "info", "Started Session {n} of User {user}."),
    ("systemd", "info", "Starting Daily apt upgrade and clean activities..."),
    ("systemd", "info", "logrotate.service: Deactivated successfully."),
    ("systemd", "info", "Finished Daily man-db regeneration."),
    ("CRON", "info", "(root) CMD (command -v debian-sa1 > /dev/null && debian-sa1 1 1)"),
    ("chronyd", "info", "Selected source 10.0.0.1 (ntp.internal)"),
    ("rsyslogd", "info", "[origin software=\"rsyslogd\" swVersion=\"8.2312.0\"] rsyslogd was HUPed"),
    ("snapd", "info", "storehelpers.go:769: cannot refresh: snap has no updates available"),
    ("kernel", "warning", "[UFW BLOCK] IN=eth0 OUT= SRC={ext_ip} DST={host_ip} PROTO=TCP SPT={port} DPT=23"),
    ("dockerd", "info", "time=\"{iso}\" level=info msg=\"Container health status changed\" status=healthy"),
    ("systemd-resolved", "warning", "Using degraded feature set UDP instead of UDP+EDNS0 for DNS server 10.0.0.2."),
    ("kernel", "err", "EXT4-fs error (device sda1): ext4_find_entry:1597: inode #2: comm ls: reading directory lblock 0"),
]

FW_PORTS = [(443, "HTTPS", "tcp", 50), (80, "HTTP", "tcp", 15), (53, "DNS", "udp", 15), (22, "SSH", "tcp", 6),
            (3389, "RDP", "tcp", 4), (445, "SMB", "tcp", 4), (23, "TELNET", "tcp", 3), (123, "NTP", "udp", 3)]

COUNTRIES = ["DE", "DE", "DE", "AT", "CH", "NL", "FR", "US", "GB", "PL", "CN", "RU", "BR"]
REGIONS = ["eu-central-1", "eu-west-1"]


def _cum(weights):
    total, out = 0, []
    for w in weights:
        total += w
        out.append(total)
    return out


def diurnal(ts):
    """Tagesgang: Faktor zwischen 0.5 (ca. 3 Uhr) und 1.5 (ca. 15 Uhr), Mittelwert 1."""
    hour = ts.hour + ts.minute / 60.0
    return 1.0 + 0.5 * math.sin(2 * math.pi * (hour - 9) / 24.0)


class World:
    """Statische Umgebung: Hosts, Services, Client-IPs. Abhängig nur vom Seed."""

    def __init__(self, profile, rng):
        self.rng = rng
        host_cfg = profile.get("hosts", {"web": 3, "app": 3, "db": 2, "fw": 1})
        self.hosts = {}
        for role_idx, (role, count) in enumerate(sorted(host_cfg.items())):
            self.hosts[role] = [
                {"name": f"{role}-{i + 1:02d}", "ip": f"10.0.{role_idx + 1}.{i + 11}", "role": role,
                 "region": REGIONS[i % len(REGIONS)]}
                for i in range(count)
            ]
        self.all_hosts = [h for role in sorted(self.hosts) for h in self.hosts[role]]
        self.linux_hosts = [h for h in self.all_hosts if h["role"] != "fw"] or self.all_hosts
        self.host_by_name = {h["name"]: h for h in self.all_hosts}

        n_services = profile.get("services", 10)
        self.services = [
            {"name": n, "role": r, "team": t, "latency": lat, "paths": p}
            for (n, r, t, lat, p) in SERVICE_CATALOG[:n_services]
        ]
        self.web_services = [s for s in self.services if s["paths"]] or [
            {"name": "frontend", "role": "web", "team": "team-web", "latency": 25, "paths": ["/"]}]
        self.app_services = [s for s in self.services if s["role"] == "app"] or [
            {"name": "order-service", "role": "app", "team": "team-shop", "latency": 80, "paths": []}]
        self.service_by_name = {s["name"]: s for s in self.services}

        n_clients = profile.get("clients", 500)
        self.clients = [self.random_public_ip() for _ in range(n_clients)]
        self.client_country = {ip: rng.choice(COUNTRIES) for ip in self.clients}
        self.client_cw = _cum([1.0 / (i + 1) ** 0.9 for i in range(n_clients)])
        self.admin_ips = [f"10.0.100.{i}" for i in range(10, 20)]

        self.ua_list = [u for u, _ in USER_AGENTS]
        self.ua_cw = _cum([w for _, w in USER_AGENTS])
        self.status_list = [s for s, _ in HTTP_STATUS]
        self.status_cw = _cum([w for _, w in HTTP_STATUS])
        self.method_list = [m for m, _ in HTTP_METHODS]
        self.method_cw = _cum([w for _, w in HTTP_METHODS])
        self.fw_cw = _cum([p[3] for p in FW_PORTS])

    def random_public_ip(self):
        rng = self.rng
        while True:
            a = rng.randint(1, 223)
            if a in (10, 127, 169, 172, 192, 100):
                continue
            return f"{a}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"

    def hosts_of(self, role):
        return self.hosts.get(role) or self.linux_hosts


class EventFactory:
    """Erzeugt Basisereignisse pro kind."""

    def __init__(self, world, rng, profile):
        self.w = world
        self.rng = rng
        self.demo_fields = bool(profile.get("demo_fields", False))
        self.counter = 0

    def _hex(self, n):
        return "%0*x" % (n, self.rng.getrandbits(n * 4))

    def _base(self, kind, ts, host, service=None):
        self.counter += 1
        ev = {
            "id": f"evt-{self.counter:010d}",
            "ts": ts,
            "kind": kind,
            "host": host,
            "service": service,
            "level": "info",
            "message": "",
            "scenario": None,
        }
        return ev

    def make(self, kind, ts):
        return getattr(self, "make_" + kind)(ts)

    def make_http(self, ts, service=None, host=None, client_ip=None, user_agent=None, path=None, status=None):
        rng, w = self.rng, self.w
        svc = service or rng.choice(w.web_services)
        host = host or rng.choice(w.hosts_of("web"))
        ev = self._base("http", ts, host, svc)
        method = rng.choices(w.method_list, cum_weights=w.method_cw)[0]
        if path is None:
            path = rng.choice(svc["paths"])
            path = path.replace("{id}", str(rng.randint(1, 5000))).replace("{q}", rng.choice(SEARCH_TERMS))
        if status is None:
            status = rng.choices(w.status_list, cum_weights=w.status_cw)[0]
        client_ip = client_ip or rng.choices(w.clients, cum_weights=w.client_cw)[0]
        size = 0 if status in (301, 302, 304) else int(rng.lognormvariate(math.log(4000), 1.0))
        duration = rng.lognormvariate(math.log(svc["latency"]), 0.5)
        if status >= 500:
            duration *= 3
        ev.update(
            method=method, path=path, status=status, bytes=size, duration_ms=round(duration, 3),
            client_ip=client_ip, country=w.client_country.get(client_ip, "DE"),
            user_agent=user_agent or rng.choices(w.ua_list, cum_weights=w.ua_cw)[0],
            referrer="-" if rng.random() < 0.6 else "https://shop.example.com/",
            user=rng.choice(USERS) if path.startswith("/api") and rng.random() < 0.3 else "-",
            trace_id=self._hex(32), span_id=self._hex(16),
        )
        ev["level"] = "info" if status < 400 else ("warn" if status < 500 else "error")
        ev["message"] = f"{method} {path} HTTP/1.1 {status}"
        return ev

    def make_auth(self, ts, host=None):
        rng, w = self.rng, self.w
        host = host or rng.choice(w.linux_hosts)
        ev = self._base("auth", ts, host)
        r = rng.random()
        pid = rng.randint(1000, 65000)
        if r < 0.45:
            user = rng.choice(ADMINS)
            ip = rng.choice(w.admin_ips)
            port = rng.randint(30000, 65000)
            ev.update(program="sshd", pid=pid, user=user, src_ip=ip, outcome="success", action="ssh_login",
                      message=f"Accepted publickey for {user} from {ip} port {port} ssh2: ED25519 SHA256:{self._hex(12)}")
        elif r < 0.55:
            user = rng.choice(INVALID_USERS)
            ip = rng.choices(w.clients, cum_weights=w.client_cw)[0]
            port = rng.randint(30000, 65000)
            ev.update(program="sshd", pid=pid, user=user, src_ip=ip, outcome="failure", action="ssh_login",
                      message=f"Failed password for invalid user {user} from {ip} port {port} ssh2")
            ev["level"] = "warn"
        elif r < 0.75:
            user = rng.choice(ADMINS)
            cmd = rng.choice(["/usr/bin/systemctl restart nginx", "/usr/bin/apt update",
                              "/usr/bin/journalctl -u order-service", "/usr/bin/docker ps"])
            ev.update(program="sudo", pid=pid, user=user, src_ip=None, outcome="success", action="sudo",
                      message=f"{user} : TTY=pts/{rng.randint(0, 3)} ; PWD=/home/{user} ; USER=root ; COMMAND={cmd}")
        elif r < 0.9:
            ev.update(program="CRON", pid=pid, user="root", src_ip=None, outcome="success", action="session_open",
                      message="pam_unix(cron:session): session opened for user root(uid=0) by (uid=0)")
        else:
            user = rng.choice(ADMINS)
            ev.update(program="sshd", pid=pid, user=user, src_ip=None, outcome="success", action="session_close",
                      message=f"pam_unix(sshd:session): session closed for user {user}")
        return ev

    def make_syslog(self, ts, host=None, program=None, severity=None, message=None):
        rng, w = self.rng, self.w
        host = host or rng.choice(w.linux_hosts)
        ev = self._base("syslog", ts, host)
        if message is None:
            program, severity, tmpl = rng.choice(SYSLOG_MESSAGES)
            if severity == "err" and rng.random() < 0.8:
                program, severity, tmpl = SYSLOG_MESSAGES[0]
            message = tmpl.format(n=rng.randint(1, 999), user=rng.choice(ADMINS),
                                  ext_ip=rng.choice(w.clients), host_ip=host["ip"],
                                  port=rng.randint(1024, 65000), iso=ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ev.update(program=program, pid=None if program == "kernel" else rng.randint(100, 9000),
                  severity=severity, message=message)
        ev["level"] = {"warning": "warn", "err": "error", "crit": "critical"}.get(severity, severity)
        return ev

    def make_app(self, ts, service=None, level=None, message=None, exception=None):
        rng, w = self.rng, self.w
        svc = service or rng.choice(w.app_services)
        host = rng.choice(w.hosts_of("app"))
        ev = self._base("app", ts, host, svc)
        if level is None:
            r = rng.random()
            level = "INFO" if r < 0.80 else "DEBUG" if r < 0.88 else "WARN" if r < 0.97 else "ERROR"
        params = dict(oid=rng.randint(100000, 999999), cid=f"C{rng.randint(1000, 9999)}",
                      pid=rng.randint(1, 5000), ms=rng.randint(3, 900), qty=rng.randint(1, 50),
                      amount=f"{rng.uniform(5, 900):.2f}", user=rng.choice(USERS))
        if message is None:
            pool = {"INFO": APP_INFO, "DEBUG": APP_DEBUG, "WARN": APP_WARN, "ERROR": APP_ERROR}[level]
            message = rng.choice(pool).format(**params)
        if level == "ERROR" and exception is None:
            exception = rng.choice(EXCEPTIONS)
        loggers = LOGGERS.get(svc["name"], [f"com.example.{svc['name'].split('-')[0]}.Service"])
        ev.update(level=level.lower(), log_level=level, message=message, logger=rng.choice(loggers),
                  thread=f"http-nio-8080-exec-{rng.randint(1, 20)}", exception=exception,
                  trace_id=self._hex(32), span_id=self._hex(16))
        return ev

    def make_firewall(self, ts, host=None):
        rng, w = self.rng, self.w
        host = host or rng.choice(w.hosts_of("fw"))
        ev = self._base("firewall", ts, host)
        port, svc_name, proto, _ = rng.choices(FW_PORTS, cum_weights=w.fw_cw)[0]
        inbound = rng.random() < 0.5
        if inbound:
            src = rng.choices(w.clients, cum_weights=w.client_cw)[0]
            dst = rng.choice(w.hosts_of("web"))["ip"]
        else:
            src = rng.choice(w.linux_hosts)["ip"]
            dst = rng.choice(w.clients)
        deny = port in (23, 445, 3389) or (inbound and port == 22) or rng.random() < 0.05
        ev.update(action="deny" if deny else "accept", src_ip=src, dst_ip=dst,
                  src_port=rng.randint(1024, 65535), dst_port=port, proto=proto, fw_service=svc_name,
                  rule_id=99 if deny else rng.choice([10, 11, 12, 20]),
                  sent_bytes=0 if deny else rng.randint(60, 200000),
                  rcvd_bytes=0 if deny else rng.randint(60, 2000000),
                  direction="inbound" if inbound else "outbound")
        ev["level"] = "warn" if deny else "info"
        ev["message"] = f"{ev['action']} {proto} {src}:{ev['src_port']} -> {dst}:{port} ({svc_name})"
        return ev

    def decorate(self, ev):
        """Zusätzliche Felder für die Columnar-Demo: Labels, Tag-Arrays (mit Duplikaten), Array of Objects."""
        if not self.demo_fields:
            return ev
        rng = self.rng
        host = ev["host"]
        svc = ev.get("service")
        ev["labels"] = {"env": "prod", "region": host["region"], "team": svc["team"] if svc else "team-ops"}
        tags = ["prod", host["role"]]
        if rng.random() < 0.2:
            tags.append("prod")
        if ev["level"] in ("error", "critical"):
            tags.append("alert-candidate")
        ev["tags"] = tags
        if ev["kind"] in ("http", "app") and rng.random() < 0.3:
            ev["links"] = [{"trace_id": self._hex(32), "span_id": self._hex(16)}
                           for _ in range(rng.randint(1, 3))]
        return ev


def jittered(ts, seconds, rng):
    return ts + timedelta(seconds=rng.random() * seconds)
