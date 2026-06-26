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
from .metrics import component_metrics

# category lands these on the SARIF "warning" rung (report/sarif.py _LEVEL_BY_CATEGORY).
CATEGORY = "architecture"
TOOL = "own-arch"

_DEFAULT_RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")


def load_rules(path: str | None = None) -> dict:
    with open(path or _DEFAULT_RULES, encoding="utf-8") as fh:
        return json.load(fh)


def _finding(rule, message, node=None, g: Graph = None, *, resource=None) -> dict:
    """A finding in findings.json shape. Anchored at a type node's source location when `node`
    is given; component-level findings (cycles/coupling with no single file) pass an explicit
    `resource` (the namespace/assembly) and carry the detail in the message."""
    loc = (node or {}).get("loc") or {}
    return {
        "tool": TOOL,
        "rule": rule,
        "category_name": CATEGORY,
        "resource": resource if resource is not None else (node or {}).get("name", ""),
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
    # ns/asm cycles have no single file: surface the first member as the resource so the
    # report/SARIF row isn't blank (the full member set is in the message).
    resource = None if level == "type" else names[0]
    msg = f"{level} dependency cycle ({len(members)} members): " + ", ".join(names)
    return _finding(rule_id, msg, anchor, g, resource=resource)


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


def check_coupling(g: Graph, cfg: dict) -> list:
    """Coupling/stability smells from Martin's metrics (arch/metrics.py), at the namespace or
    assembly level. Two sub-rules, each opt-in via config:

      * SDP — Stable Dependencies Principle: a stable component depending on a *less* stable
        one (I(from) + min_gap < I(to)). Dependencies should run toward stability, not away.
      * unstable hub — a component that is both widely used (high Ca) and widely depending
        (high Ce): a change there ripples both ways.

    Component-level, so findings carry the namespace/assembly as `resource` (no single file)."""
    if not cfg:
        return []
    key = cfg.get("level", "namespace")
    metrics = component_metrics(g, key)
    out = []

    sdp = cfg.get("sdp")
    if sdp:
        rid = sdp.get("id", "ARCH-SDP")
        gap, min_ce = sdp.get("min_gap", 0.3), sdp.get("min_ce", 3)
        adj, _ = g.component_graph(key)
        for p, deps in adj.items():
            mp = metrics.get(p)
            if not mp or mp["ce"] < min_ce:                 # ignore trivially-coupled components
                continue
            for q in deps:
                mq = metrics.get(q)
                if mq and mp["instability"] + gap < mq["instability"]:
                    out.append(_finding(
                        rid, f"Stable Dependencies violation: {key} {p} (I={mp['instability']}) "
                             f"depends on less-stable {q} (I={mq['instability']})", resource=p))

    hub = cfg.get("unstable_hub")
    if hub:
        rid = hub.get("id", "ARCH-UNSTABLE-HUB")
        min_ca, min_ce = hub.get("min_ca", 6), hub.get("min_ce", 6)
        for c, m in metrics.items():
            if m["ca"] >= min_ca and m["ce"] >= min_ce:
                out.append(_finding(
                    rid, f"unstable hub: {key} {c} is both widely used (Ca={m['ca']}) and widely "
                         f"depending (Ce={m['ce']}); I={m['instability']}", resource=c))
    return out


def run(g: Graph, rules: dict | None = None) -> list:
    """All rules over the graph → a flat findings list (findings.json shape)."""
    rules = rules or load_rules()
    findings = []
    findings += check_layering(g, rules.get("layers", []))
    findings += check_cycles(g, rules.get("cycles", {}))
    findings += check_god_class(g, rules.get("god_class", {}))
    findings += check_coupling(g, rules.get("coupling", {}))
    return findings
