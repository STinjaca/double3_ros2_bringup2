#!/usr/bin/env python3
"""Sanitiza grabaciones de eventos del D3 (JSON por línea) antes de commitearlas como fixtures.

Las grabaciones crudas (`d3_agent.py --record`) pueden contener SSID, IPs, MACs, geolocalización,
seriales y UUIDs. Este script redacta esas claves y cualquier IP/MAC en valores de texto.

Uso: python3 tools/sanitize_fixtures.py recordings/lab.raw.jsonl d3_sim/fixtures/lab.jsonl
Revisa SIEMPRE la salida a mano antes del commit.
"""
import json
import re
import sys

SENSITIVE_TOKENS = {
    "ssid", "bssid", "ip", "ipv4", "ipv6", "mac", "location", "lat", "latitude", "lon", "lng",
    "longitude", "serial", "uuid", "identity", "hostname", "password", "token", "email", "account",
    "address", "gateway", "dns", "nameserver", "wifi", "network", "geo", "city", "country"}
TOKEN_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
DROP_EVENTS = {"DRNetwork.location", "DRNetwork.scan", "DRBluetooth.list", "DRBluetooth.scan",
               "DRNetwork.connections", "DRSystem.screenshot", "DRCamera.photo"}
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")


def is_sensitive(key):
    """`internalIp`, `wifi_ssid`, `serialNumber` -> True; `pipeline`, `tilt` -> False."""
    return any(tok.lower() in SENSITIVE_TOKENS for tok in TOKEN_RE.findall(key))


def scrub(value):
    if isinstance(value, dict):
        return {k: ("<REDACTED>" if is_sensitive(k) else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = IP_RE.sub("192.0.2.1", value)  # public-safe
        return MAC_RE.sub("00:00:00:00:00:00", value)  # public-safe
    return value


def main(src, dst):
    kept = dropped = 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                dropped += 1
                continue
            name = "%s.%s" % (event.get("class", ""), event.get("key", ""))
            if name in DROP_EVENTS:
                dropped += 1
                continue
            fout.write(json.dumps(scrub(event), ensure_ascii=False) + "\n")
            kept += 1
    print("Eventos conservados: %d, descartados: %d -> %s" % (kept, dropped, dst))
    print("Revisa el archivo a mano antes del commit.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
