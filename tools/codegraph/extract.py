#!/usr/bin/env python3
"""Grafo de código del bringup NAOqi (SinfonIA) cruzado con el contrato del D3.

Recorre los repos naoqi_* sin ejecutarlos (análisis estático):
  - nodos Python (ast): create_service / create_publisher / create_subscription, el callback de cada
    interfaz y los métodos NAOqi que ese callback invoca (self.al_x.metodo -> ALServicio.metodo),
  - driver C++ (regex): registerSubscriber / registerService / create_server,
  - YAML del bringup: converters.*.topic (topics que publica el driver).
Luego lo cruza con contract/contract.yaml y exporta:
  out/graph.json, out/graph.graphml, out/graph.mmd (Mermaid) y out/drift.txt.

Uso:
  python3 tools/codegraph/extract.py --src ../ros2_naoqi_ws/src [--contract contract/contract.yaml]
Sale con código 1 si hay interfaces en el código que faltan en el contrato (sirve en CI).
"""
import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from xml.sax.saxutils import escape

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CREATE_KINDS = {"create_service": "srv", "create_publisher": "pub", "create_subscription": "sub"}


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = set()

    def node(self, node_id, kind, **attrs):
        entry = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind})
        entry.update({k: v for k, v in attrs.items() if v is not None})
        return node_id

    def edge(self, src, dst, rel):
        self.edges.add((src, dst, rel))


# ----------------------------------------------------------------------------- Python (ast)
class PyNodeVisitor(ast.NodeVisitor):
    """Extrae interfaces ROS y llamadas NAOqi de un archivo de nodo rclpy."""

    def __init__(self):
        self.imports = {}            # nombre -> "pkg/kind/Type"
        self.node_name = None
        self.interfaces = []         # (kind, name, type, callback)
        self.attr_to_service = {}    # al_motion -> ALMotion
        self.methods = {}            # nombre -> ast.FunctionDef

    def visit_ImportFrom(self, node):
        if node.module and re.match(r"^\w+\.(msg|srv|action)$", node.module):
            pkg, kind = node.module.split(".")
            for alias in node.names:
                self.imports[alias.asname or alias.name] = "%s/%s/%s" % (pkg, kind, alias.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.methods[node.name] = node
        self.generic_visit(node)

    def visit_Assign(self, node):
        # self.al_motion = self._service("ALMotion") / session.service("ALMotion")
        service = _al_string_in_call(node.value)
        if service:
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    self.attr_to_service[target.attr] = service
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "__init__" and node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str) and self.node_name is None:
                self.node_name = node.args[0].value
        if name in CREATE_KINDS and len(node.args) >= 2:
            type_node, topic_node = node.args[0], node.args[1]
            type_name = getattr(type_node, "id", None) or getattr(type_node, "attr", None)
            topic = topic_node.value if isinstance(topic_node, ast.Constant) else None
            callback = None
            if len(node.args) >= 3 and isinstance(node.args[2], ast.Attribute):
                callback = node.args[2].attr
            for kw in node.keywords:
                if kw.arg == "callback" and isinstance(kw.value, ast.Attribute):
                    callback = kw.value.attr
            if topic:
                self.interfaces.append((CREATE_KINDS[name], topic, self.imports.get(type_name, type_name), callback))
        self.generic_visit(node)

    def naoqi_calls(self, method_name, depth=0, seen=None):
        """Métodos NAOqi (ALServicio.metodo) alcanzables desde un callback (sigue self.metodo())."""
        seen = seen if seen is not None else set()
        if method_name in seen or method_name not in self.methods or depth > 3:
            return set()
        seen.add(method_name)
        calls = set()
        for node in ast.walk(self.methods[method_name]):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            # self.al_motion.moveTo(...)
            if isinstance(owner, ast.Attribute) and owner.attr in self.attr_to_service:
                calls.add("%s.%s" % (self.attr_to_service[owner.attr], node.func.attr))
            # self._service("ALMotion").moveTo(...)
            elif isinstance(owner, ast.Call) and _al_string_in_call(owner):
                calls.add("%s.%s" % (_al_string_in_call(owner), node.func.attr))
            # self.helper(...)
            elif isinstance(owner, ast.Name) and owner.id == "self":
                calls |= self.naoqi_calls(node.func.attr, depth + 1, seen)
        return calls


def _al_string_in_call(node):
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.match(r"^AL[A-Z]\w+$", arg.value):
                return arg.value
    return None


def scan_python(src, graph, found):
    for pkg in sorted(os.listdir(src)):
        pkg_dir = os.path.join(src, pkg, pkg)
        if not pkg.startswith("naoqi_") or not os.path.isdir(pkg_dir):
            continue
        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith("_node.py"):
                continue
            path = os.path.join(pkg_dir, fname)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            visitor = PyNodeVisitor()
            visitor.visit(tree)
            ros_node = visitor.node_name or fname[:-3]
            pkg_id = graph.node("pkg:" + pkg, "package", label=pkg, repo="SinfonIA")
            node_id = graph.node("node:" + ros_node, "ros_node", label=ros_node, file=os.path.relpath(path, src))
            graph.edge(pkg_id, node_id, "contains")
            for kind, name, msg_type, callback in visitor.interfaces:
                iface = add_interface(graph, name, kind, msg_type)
                graph.edge(node_id, iface, kind)
                found[name] = {"kind": kind, "type": msg_type, "node": ros_node}
                for call in sorted(visitor.naoqi_calls(callback) if callback else ()):
                    api = graph.node("naoqi:" + call, "naoqi_api", label=call, service=call.split(".")[0])
                    graph.edge(iface, api, "calls")


def add_interface(graph, name, kind, msg_type):
    iface = graph.node("iface:" + name, "interface", label=name, ros_kind=kind, type=msg_type)
    if msg_type and "/" in str(msg_type):
        type_id = graph.node("type:" + msg_type, "msg_type", label=msg_type)
        graph.edge(iface, type_id, "typed_by")
    return iface


# ----------------------------------------------------------------------------- driver C++ + YAML
def scan_driver(src, graph, found):
    driver = os.path.join(src, "naoqi_driver2")
    if not os.path.isdir(driver):
        return
    pkg_id = graph.node("pkg:naoqi_driver2", "package", label="naoqi_driver2", repo="SinfonIA")
    node_id = graph.node("node:naoqi_driver", "ros_node", label="naoqi_driver", file="naoqi_driver2/src/naoqi_driver.cpp")
    graph.edge(pkg_id, node_id, "contains")
    with open(os.path.join(driver, "src", "naoqi_driver.cpp"), encoding="utf-8") as fh:
        code = fh.read()
    for cls, args in re.findall(r"registerSubscriber\(\s*boost::make_shared<[\w:]*?(\w+)>\(([^)]*)\)", code):
        names = re.findall(r'"([^"]+)"', args)[1:]
        for name in names:
            iface = add_interface(graph, name, "sub", None)
            graph.edge(node_id, iface, "sub")
            found.setdefault(name, {"kind": "sub", "type": None, "node": "naoqi_driver"})
    for cls, args in re.findall(r"registerService\(\s*boost::make_shared<[\w:]*?(\w+)>\(([^)]*)\)", code):
        names = re.findall(r'"([^"]+)"', args)
        if len(names) >= 2:
            iface = add_interface(graph, names[1], "srv", None)
            graph.edge(node_id, iface, "srv")
            found.setdefault(names[1], {"kind": "srv", "type": None, "node": "naoqi_driver"})
    if re.search(r"create_server<Listen>", open(os.path.join(driver, "src", "actions", "listen.cpp")).read()):
        iface = add_interface(graph, "listen", "action", "naoqi_bridge_msgs/action/Listen")
        graph.edge(node_id, iface, "action")
        found.setdefault("listen", {"kind": "action", "type": "naoqi_bridge_msgs/action/Listen", "node": "naoqi_driver"})
    # Topics publicados: claves converters.<x>.*topic del YAML del bringup (Pepper + NAO)
    config_dir = os.path.join(src, "naoqi_bringup2_sinfonIA", "config")
    for cfg in sorted(os.listdir(config_dir)) if os.path.isdir(config_dir) else ():
        with open(os.path.join(config_dir, cfg), encoding="utf-8") as fh:
            params = (yaml.safe_load(fh) or {}).get("naoqi_driver", {}).get("ros__parameters", {})
        for key, value in params.items():
            if key.startswith("converters.") and key.endswith("topic") and "recorder" not in key:
                iface = add_interface(graph, str(value), "pub", None)
                graph.edge(node_id, iface, "pub")
                found.setdefault(str(value), {"kind": "pub", "type": None, "node": "naoqi_driver"})


# ----------------------------------------------------------------------------- contrato
def merge_contract(contract, graph, found):
    drift = []
    by_name = {entry["name"]: entry for entry in contract["interfaces"]}
    for entry in contract["interfaces"]:
        iface = add_interface(graph, entry["name"], entry["kind"], entry["type"])
        d3 = entry.get("d3", {})
        status = d3.get("status", "planned")
        graph.nodes[iface]["d3_status"] = status
        if d3.get("node") and d3["node"] != "-":
            d3_node = graph.node("d3node:" + d3["node"], "d3_node", label=d3["node"])
            graph.edge(iface, d3_node, "implemented_by")
        if d3.get("impl") and d3["impl"] != "-":
            impl = graph.node("d3impl:" + d3["impl"], "d3_impl", label=d3["impl"])
            graph.edge(iface, impl, "maps_to")
    for name, info in sorted(found.items()):
        entry = by_name.get(name) or by_name.get(name.lstrip("/"))
        if entry is None:
            drift.append("FALTA EN CONTRATO: %s (%s, %s) del nodo %s" % (name, info["kind"], info["type"], info["node"]))
        elif info["type"] and entry["type"] != info["type"]:
            drift.append("TIPO DISTINTO: %s código=%s contrato=%s" % (name, info["type"], entry["type"]))
    for name, entry in sorted(by_name.items()):
        origin = entry.get("naoqi", {}).get("node", "-")
        if entry.get("implicit"):
            continue  # p. ej. camera_info (image_transport) o robot_description (fijo en el driver)
        if origin not in ("-", "") and name not in found and name.lstrip("/") not in found:
            drift.append("SOLO EN CONTRATO: %s (origen declarado %s)" % (name, origin))
    return drift


# ----------------------------------------------------------------------------- exportadores
def to_graphml(graph):
    keys = sorted({k for n in graph.nodes.values() for k in n if k != "id"})
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    out += ['  <key id="%s" for="node" attr.name="%s" attr.type="string"/>' % (k, k) for k in keys]
    out += ['  <key id="rel" for="edge" attr.name="rel" attr.type="string"/>', '  <graph edgedefault="directed">']
    for node in graph.nodes.values():
        out.append('    <node id="%s">' % escape(node["id"]))
        out += ['      <data key="%s">%s</data>' % (k, escape(str(node[k]))) for k in keys if k in node]
        out.append("    </node>")
    for src, dst, rel in sorted(graph.edges):
        out.append('    <edge source="%s" target="%s"><data key="rel">%s</data></edge>' % (escape(src), escape(dst), rel))
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out) + "\n"


STATUS_CLASS = {"supported": "ok", "partial": "partial", "noop": "noop", "unsupported": "no", "planned": "planned"}


def to_mermaid(graph):
    """Vista resumida: nodo NAOqi -> interfaz (coloreada por estado D3) -> nodo D3."""
    ids = {}

    def mid(node_id):
        return ids.setdefault(node_id, "n%d" % len(ids))

    lines = ["flowchart LR",
             "  classDef ok fill:#d1fae5,stroke:#059669", "  classDef partial fill:#fef3c7,stroke:#d97706",
             "  classDef noop fill:#e0e7ff,stroke:#4f46e5", "  classDef no fill:#fee2e2,stroke:#dc2626",
             "  classDef planned fill:#f3f4f6,stroke:#6b7280,stroke-dasharray:4"]
    for src, dst, rel in sorted(graph.edges):
        s, d = graph.nodes[src], graph.nodes[dst]
        if s["kind"] == "ros_node" and d["kind"] == "interface" or rel == "implemented_by":
            lines.append('  %s["%s"] -->|%s| %s["%s"]' % (mid(src), s["label"], rel, mid(dst), d["label"]))
    for node_id, node in graph.nodes.items():
        if node["kind"] == "interface" and node_id in ids:
            lines.append("  class %s %s" % (ids[node_id], STATUS_CLASS.get(node.get("d3_status"), "planned")))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default=os.path.abspath(os.path.join(ROOT, "..", "ros2_naoqi_ws", "src")))
    parser.add_argument("--contract", default=os.path.join(ROOT, "contract", "contract.yaml"))
    parser.add_argument("--out", default=os.path.join(HERE, "out"))
    args = parser.parse_args(argv)
    if not os.path.isdir(args.src):
        sys.exit("No encuentro los repos naoqi_* en %s (usa --src)" % args.src)
    graph, found = Graph(), {}
    scan_python(args.src, graph, found)
    scan_driver(args.src, graph, found)
    with open(args.contract, encoding="utf-8") as fh:
        contract = yaml.safe_load(fh)
    drift = merge_contract(contract, graph, found)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "graph.json"), "w", encoding="utf-8") as fh:
        json.dump({"nodes": list(graph.nodes.values()),
                   "edges": [{"source": s, "target": t, "rel": r} for s, t, r in sorted(graph.edges)]},
                  fh, indent=1, ensure_ascii=False)
    with open(os.path.join(args.out, "graph.graphml"), "w", encoding="utf-8") as fh:
        fh.write(to_graphml(graph))
    with open(os.path.join(args.out, "graph.mmd"), "w", encoding="utf-8") as fh:
        fh.write(to_mermaid(graph))
    with open(os.path.join(args.out, "drift.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(drift) + ("\n" if drift else ""))
    kinds = defaultdict(int)
    for node in graph.nodes.values():
        kinds[node["kind"]] += 1
    print("Grafo: %d nodos (%s), %d aristas -> %s" % (
        len(graph.nodes), ", ".join("%s=%d" % kv for kv in sorted(kinds.items())), len(graph.edges), args.out))
    print("Interfaces encontradas en el código: %d" % len(found))
    for line in drift:
        print("  " + line)
    missing = [d for d in drift if d.startswith(("FALTA", "TIPO"))]
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
