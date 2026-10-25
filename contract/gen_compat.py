#!/usr/bin/env python3
"""Genera contract/COMPATIBILITY.md a partir de contract/contract.yaml (no editar el .md a mano)."""
import os
from collections import Counter, OrderedDict

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = {"supported": "✅ supported", "partial": "🟡 partial", "noop": "🔵 noop",
        "unsupported": "⛔ unsupported", "planned": "🕓 planned"}
KIND = {"pub": "pub", "sub": "sub", "srv": "srv", "action": "action"}


def cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def main():
    with open(os.path.join(HERE, "contract.yaml"), encoding="utf-8") as fh:
        contract = yaml.safe_load(fh)
    groups = OrderedDict()
    for entry in contract["interfaces"]:
        groups.setdefault(entry["naoqi"].get("node", "-"), []).append(entry)
    counts = Counter(e["d3"]["status"] for e in contract["interfaces"])
    lines = [
        "# Matriz de compatibilidad NAOqi → Double 3",
        "",
        "> Generado por `contract/gen_compat.py` desde `contract/contract.yaml`. No editar a mano.",
        "",
        "Namespace por defecto: `/%s` (en el original: `/nao` o `/pepper`)." % contract["namespace_default"],
        "",
        "| Estado | Interfaces |", "|---|---|",
    ]
    lines += ["| %s | %d |" % (ICON[s], counts.get(s, 0)) for s in ICON]
    lines += ["", "- **supported**: implementado con el hardware del D3.",
              "- **partial**: implementado con limitaciones (ver notas).",
              "- **noop**: responde éxito sin hacer nada (no aplica al D3; lo llama la secuencia de arranque).",
              "- **unsupported**: el servicio existe y responde `success=false, \"unsupported on D3\"`.",
              "- **planned**: fase posterior.", ""]
    for origin, entries in groups.items():
        title = origin if origin != "-" else "Nuevas en el D3"
        lines += ["## %s" % title, "", "| Interfaz | Tipo | NAOqi | D3 | Estado | Notas |", "|---|---|---|---|---|---|"]
        for e in entries:
            lines.append("| `%s` (%s) | `%s` | %s | %s | %s | %s |" % (
                cell(e["name"]), KIND[e["kind"]], cell(e["type"]), cell(e["naoqi"].get("api")),
                cell(e["d3"].get("impl")), ICON[e["d3"]["status"]], cell(e["d3"].get("notes"))))
        lines.append("")
    with open(os.path.join(HERE, "COMPATIBILITY.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("COMPATIBILITY.md: %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())))


if __name__ == "__main__":
    main()
