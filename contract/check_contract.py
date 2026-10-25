#!/usr/bin/env python3
"""Compara el grafo ROS 2 en vivo con contract/contract.yaml.

Requisitos: el bringup corriendo (p. ej. `make sim`) y el entorno ROS cargado.
Revisa que cada interfaz requerida exista bajo /<namespace>/ con el mismo tipo:
  - servicios y acciones: siempre (también los `unsupported`, que deben responder con error claro)
  - topics: solo los de status supported/partial (los unsupported/planned no se crean)

Uso: python3 contract/check_contract.py --namespace d3 [--timeout 20]
"""
import argparse
import os
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIRED_TOPIC_STATUS = {"supported", "partial"}


def ros2_list(kind):
    out = subprocess.run(["ros2", kind, "list", "-t"], capture_output=True, text=True, timeout=30).stdout
    result = {}
    for line in out.splitlines():
        if " [" in line:
            name, types = line.split(" [", 1)
            result[name.strip()] = {t.strip() for t in types.rstrip("]").split(",")}
    return result


def full_name(namespace, name):
    return name if name.startswith("/") else "/%s/%s" % (namespace, name) if namespace else "/" + name


def required(entry):
    status = entry.get("d3", {}).get("status", "planned")
    if entry["kind"] in ("srv", "action"):
        return status != "planned"
    return status in REQUIRED_TOPIC_STATUS


def check(contract, namespace):
    live = {"topic": ros2_list("topic"), "service": ros2_list("service"), "action": ros2_list("action")}
    kind_map = {"pub": "topic", "sub": "topic", "srv": "service", "action": "action"}
    ok, problems = [], []
    for entry in contract["interfaces"]:
        if not required(entry):
            continue
        name = full_name(namespace, entry["name"])
        found = live[kind_map[entry["kind"]]].get(name)
        if found is None:
            problems.append("FALTA   %-8s %-45s %s" % (entry["kind"], name, entry["type"]))
        elif entry["type"] not in found:
            problems.append("TIPO    %-8s %-45s esperado %s, encontrado %s" % (entry["kind"], name, entry["type"], sorted(found)))
        else:
            ok.append(name)
    return ok, problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="d3")
    parser.add_argument("--contract", default=os.path.join(HERE, "contract.yaml"))
    parser.add_argument("--timeout", type=float, default=20.0, help="segundos para esperar a que todo aparezca")
    args = parser.parse_args()
    with open(args.contract, encoding="utf-8") as fh:
        contract = yaml.safe_load(fh)
    deadline = time.time() + args.timeout
    while True:
        ok, problems = check(contract, args.namespace.strip("/"))
        if not problems or time.time() > deadline:
            break
        time.sleep(2.0)
    total = len(ok) + len(problems)
    for name in ok:
        print("OK      %s" % name)
    for line in problems:
        print(line)
    print("\n%d/%d interfaces del contrato presentes con el tipo correcto en /%s" % (len(ok), total, args.namespace))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
