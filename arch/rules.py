"""Architecture rules engine (Own.NET Auditor docs/own-net-auditor.md §3, phase 3).

Runs declarative rules (arch/rules.json) over the dependency Graph and emits findings in
the SAME shape as sts_audit/findings.json, so they flow through the existing SARIF export,
baseline diff and dashboard unchanged — tool `own-arch`, category `architecture`.

Three rule kinds, each a different shape of "the structure is wrong":
  * layering  — a forbidden dependency direction (UI → SQL, Domain → WPF). One edge, one finding.
  * cycles    — strongly-connected groups of types/namespaces/assemblies (mutual dependency).
  * god_class — a composite signal: a single type that is large on several axes at once.

Everything here is pure structure over graph.json; no source, no .NET.
"""
from __future__ import annotations

import json
import os

from .graph import Graph, match_any

# category lands these on the SARIF "warning" rung (report/sarif.py _LEVEL_BY_CATEGORY).
CATEGORY = "architecture"
TOOL = "own-arch"

_DEFAULT_RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")


def load_rules(path: str | None = None) -> dict:
    with open(path or _DEFAULT_RULES, encoding="utf-8") as fh:
        return json.load(fh)


def _finding(rule, message, node, g: Graph) -> dict:
    """A finding in findings.json shape, anchored at a type node's source location."""
    loc = (node or {}).get("loc") or {}
    return {
        "tool": TOOL,
        "rule": rule,
        "category_name": CATEGORY,
        "resource": (node or {}).get("name", ""),
        "path": loc.get("file", ""),
        "line": loc.get("line", 0),
        "message": message,
        "suppressed": False,
    }


def _targets(g: Graph, nid: str) -> tuple:
    """Strings a layering `to`/`from` pattern may match a node against: its namespace, its
    fully-qualified name, and its assembly — so a rule can name a layer, a type, or a dll."""
    n = g.node(nid)
    ns, name, asm = n.get("namespace", ""), n.get("name", ""), n.get("assembly", "")
    fq = f"{ns}.{name}" if ns and name else name
    return tuple(s for s in (ns, fq, asm, name) if s)


def check_layering(g: Graph, rules: list) -> list:
    """Forbidden dependency directions. Source must be internal (ours to fix); the target
    may be internal or a framework/third-party type."""
    out = []
    for rule in rules or []:
        rid = rule["id"]
        frm, to, msg = rule.get("from", []), rule.get("to", []), rule.get("message", "")
        for e in g.unique_edges():
            a, b = e.get("from"), e.get("to")
            if a not in g.nodes or not g._internal(a):
                continue
            if not any(match_any(s, frm) for s in _targets(g, a)):
                continue
            if not any(match_any(s, to) for s in _targets(g, b)):
                continue
            out.append(_finding(
                rid, f"{msg}: {g.name(a)} → {g.name(b)}", g.node(a), g))
    return out


def _cycle_finding(g: Graph, rule_id, level, members) -> dict:
    """Anchor a cycle finding at its lexically-first member, listing the SCC's members.

    The members are rendered as an unordered set, NOT an arrow chain: an SCC tells us the
    group is mutually reachable, but not the order of a traversable loop, so `a → b → c → a`
    would invent edges that may not exist. The set is the honest statement."""
    names = sorted(g.name(m) if level == "type" else (m or "(none)") for m in members)
    anchor = g.node(sorted(members)[0]) if level == "type" else None
    msg = f"{level} dependency cycle ({len(members)} members): " + ", ".join(names)
    return _finding(rule_id, msg, anchor, g)


def check_cycles(g: Graph, cfg: dict) -> list:
    out = []
    cfg = cfg or {}
    if cfg.get("type"):
        for comp in g.type_cycles():
            out.append(_cycle_finding(g, "ARCH-CYCLE-TYPE", "type", comp))
    if cfg.get("namespace"):
        for comp in g.namespace_cycles():
            out.append(_cycle_finding(g, "ARCH-CYCLE-NS", "namespace", comp))
    if cfg.get("assembly"):
        for comp in g.assembly_cycles():
            out.append(_cycle_finding(g, "ARCH-CYCLE-ASM", "assembly", comp))
    return out


_GOD_AXES = (("methods", "methods"), ("fields", "fields"),
             ("loc", "LOC"), ("deps_out", "outgoing deps"))


def check_god_class(g: Graph, cfg: dict) -> list:
    """Composite: a type that crosses several size thresholds at once. One axis is normal;
    crossing `min_signals` of them together is the smell. `deps_out` is taken from the graph
    (fan-out) so it can't be gamed by a stale metric in the export."""
    if not cfg:
        return []
    rid = cfg.get("id", "ARCH-GOD-CLASS")
    min_signals = cfg.get("min_signals", 2)
    out = []
    for nid in g.type_ids():
        n = g.node(nid)
        metrics = dict(n.get("metrics") or {})
        metrics["deps_out"] = g.fan_out(nid)        # internal + external fan-out (deduped)
        signals = []
        for key, label in _GOD_AXES:
            threshold = cfg.get(key)
            if threshold is not None and metrics.get(key, 0) >= threshold:
                signals.append(f"{label} {metrics.get(key, 0)} ≥ {threshold}")
        if len(signals) >= min_signals:
            out.append(_finding(
                rid, f"god class {g.name(nid)}: " + "; ".join(signals), n, g))
    return out


def run(g: Graph, rules: dict | None = None) -> list:
    """All rules over the graph → a flat findings list (findings.json shape)."""
    rules = rules or load_rules()
    findings = []
    findings += check_layering(g, rules.get("layers", []))
    findings += check_cycles(g, rules.get("cycles", {}))
    findings += check_god_class(g, rules.get("god_class", {}))
    return findings
