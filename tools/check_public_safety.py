#!/usr/bin/env python3
"""Revisa los archivos staged (o los pasados por argumento) antes de un commit en un repo público.

Rechaza:
  - IPs de redes privadas/institucionales (10/8, 172.16/12, 192.168/16, 157.253/16 Uniandes)
  - Direcciones MAC
  - Archivos de más de 5 MB
  - Asignaciones literales de contraseñas/tokens
Permitido: 127.0.0.1, 0.0.0.0, 192.0.2.0/24 (RFC 5737), y líneas marcadas con `public-safe`.

Uso: python3 tools/check_public_safety.py [archivos...]
"""
import ipaddress
import os
import re
import subprocess
import sys

MAX_BYTES = 5 * 1024 * 1024
BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "157.253.0.0/16", "100.64.0.0/10")]
IP_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
MAC_RE = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
SECRET_KEYS = r"(?i)\b\w*(password|passwd|token|secret|api_key)\w*\b"
# En código: solo literales entre comillas (`token = "abc..."`), no expresiones (`token = str(...)`).
SECRET_QUOTED_RE = re.compile(SECRET_KEYS + r"""\s*[:=]\s*(["'])(?!changeme|<|\$\{)[^"'\s]{6,}\2""")
# En archivos de configuración también valores sin comillas que no sean expresiones.
SECRET_BARE_RE = re.compile(SECRET_KEYS + r"""\s*[:=]\s*(?!changeme|<|\$|\{|none\b|null\b|true\b|false\b)[^\s"'#().$]{6,}\s*(#.*)?$""")
CONFIG_SUFFIX = (".yaml", ".yml", ".sh", ".service", ".toml", ".ini", ".cfg", ".conf")
SKIP_SUFFIX = (".svg",)


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def check_file(path):
    problems = []
    if not os.path.isfile(path):
        return problems
    if os.path.getsize(path) > MAX_BYTES:
        return ["archivo de más de 5 MB"]
    if path.endswith(SKIP_SUFFIX) or path.endswith("check_public_safety.py"):
        return problems
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except (UnicodeDecodeError, OSError):
        return problems
    for lineno, line in enumerate(lines, 1):
        if "public-safe" in line:
            continue
        for match in IP_RE.finditer(line):
            try:
                ip = ipaddress.ip_address(match.group(1))
            except ValueError:
                continue
            if any(ip in net for net in BLOCKED_NETS):
                problems.append("línea %d: IP de red privada/institucional %s" % (lineno, ip))
        if MAC_RE.search(line):
            problems.append("línea %d: dirección MAC" % lineno)
        name = os.path.basename(path)
        is_config = name.startswith(".env") or name.endswith(CONFIG_SUFFIX)
        if SECRET_QUOTED_RE.search(line) or (is_config and SECRET_BARE_RE.search(line)):
            problems.append("línea %d: posible secreto literal" % lineno)
    return problems


def main(argv):
    files = argv or staged_files()
    failed = False
    for path in files:
        for problem in check_file(path):
            failed = True
            print("%s: %s" % (path, problem))
    if failed:
        print("\nCommit bloqueado: este repo es PÚBLICO. Usa variables de entorno, <PLACEHOLDER> o 192.0.2.x.")
        print("Si es un falso positivo, marca la línea con un comentario `public-safe`.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
