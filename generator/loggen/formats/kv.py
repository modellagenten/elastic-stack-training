import zlib

PROTO_NUM = {"tcp": 6, "udp": 17}


def render(ev):
    ts = ev["ts"]
    action = ev["action"]
    return (f'date={ts:%Y-%m-%d} time={ts:%H:%M:%S} devname="{ev["host"]["name"]}" '
            f'devid="FGT60F{zlib.crc32(ev["host"]["name"].encode()):010d}" type="traffic" subtype="forward" '
            f'level="{"warning" if action == "deny" else "notice"}" srcip={ev["src_ip"]} srcport={ev["src_port"]} '
            f'dstip={ev["dst_ip"]} dstport={ev["dst_port"]} proto={PROTO_NUM[ev["proto"]]} '
            f'action="{action}" policyid={ev["rule_id"]} service="{ev["fw_service"]}" '
            f'direction="{ev["direction"]}" sentbyte={ev["sent_bytes"]} rcvdbyte={ev["rcvd_bytes"]}')
