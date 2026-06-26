"""Architecture drift — diff two graph snapshots (Own.NET Auditor docs/own-net-auditor.md §3,
phase 4, killer feature #1).

Phase 2's baseline diff compares *findings* (fingerprints) — it sees a new violation only once
it crosses a rule threshold. Drift is the complement: it compares the **structure itself**
between two runs (baseline = main's graph, current = the PR's graph) and reports what *moved* —
coupling creeping up, a brand-new dependency edge, a freshly-introduced cycle — before any of it
trips a rule. That's the "PR raised coupling in Broker.Documents by 18%, new edge to
System.Data.SqlClient, new cycle Documents↔Services" report a reviewer reads at a glance.

Pure structure over two `graph.json`s (via arch.metrics); no .NET, CI-testable. A snapshot is
compact (component metrics + the namespace dependency surface + the cycle set) and is a user
artifact created on the stand — kept out of git and fed to CI like phase-2's baseline.
"""
from __future__ import annotations

from .graph import Graph, match_any
from .metrics import component_metrics

SCHEMA = "ownAudit/arch-drift/v1"

# risk ladder shared by the report and the gate.
RISK_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


def _fqn(g: Graph, nid: str) -> str:
    """Fully-qualified type name (namespace.Name). Used as the cycle-member identity so two
    distinct cycles that happen to share short names (Service/Repository in different
    namespaces) don't collapse to the same key and mask a newly-introduced cycle."""
    ns, name = g.namespace(nid), g.name(nid)
    return f"{ns}.{name}" if ns else name


def snapshot(g: Graph, key: str = "namespace") -> dict:
    """A compact, comparable, committable summary of a graph's architecture:
    per-component coupling metrics, the component-level dependency surface (incl. edges to
    external framework namespaces — that's where 'new SQL dependency' lives), and the cycle set."""
    metrics = component_metrics(g, key)
    comp_all = {nid: (g.node(nid).get(key) or "(none)") for nid in g.nodes}  # incl. external
    edges = set()
    for e in g.unique_edges():
        a, b = comp_all.get(e.get("from")), comp_all.get(e.get("to"))
        if a is not None and b is not None and a != b:
            edges.add((a, b))
    cycles = []
    for comp in g.type_cycles():       # FQ names: identity, not just display (see _fqn)
        cycles.append({"level": "type", "members": sorted(_fqn(g, m) for m in comp)})
    for comp in g.namespace_cycles():
        cycles.append({"level": "namespace", "members": sorted(m or "(none)" for m in comp)})
    for comp in g.assembly_cycles():
        cycles.append({"level": "assembly", "members": sorted(m or "(none)" for m in comp)})
    return {"schema": SCHEMA, "level": key, "components": metrics,
            "edges": sorted(list(e) for e in edges), "cycles": cycles}


def as_snapshot(data, key: str = "namespace") -> dict:
    """Accept a saved drift snapshot, a raw graph.json dict, or a built Graph — return a
    snapshot at component level `key`. Lets the CLI take either a committed baseline snapshot
    or a fresh graph. A saved snapshot built at a DIFFERENT level is rejected (its components
    and edges are keyed by the other level, so diffing would emit bogus new/removed items)."""
    if isinstance(data, Graph):
        return snapshot(data, key)
    if isinstance(data, dict) and data.get("schema") == SCHEMA:
        saved = data.get("level", key)
        if saved != key:
            raise ValueError(f"baseline snapshot is at level {saved!r} but the diff is requested "
                             f"at level {key!r}; re-create the snapshot at level {key!r}")
        return data
    return snapshot(Graph(data), key)


def _cycle_key(c) -> tuple:
    return (c["level"], tuple(c["members"]))


def diff(base: dict, cur: dict, cfg: dict | None = None) -> dict:
    """Structured drift between two snapshots. Each change is one risk-tagged item; the gate
    and report consume `items`. Thresholds are config-driven (arch/rules.json `drift` block)."""
    cfg = cfg or {}
    ce_jump = cfg.get("ce_jump", 5)
    ce_pct = cfg.get("ce_pct", 0.25)
    inst_swing = cfg.get("inst_swing", 0.2)
    sensitive = cfg.get("sensitive_targets", [])
    bcomp, ccomp = base.get("components", {}), cur.get("components", {})
    items = []

    # --- cycles: introducing one is the worst drift; resolving one is good news -----------
    bset = {_cycle_key(c) for c in base.get("cycles", [])}
    cset = {_cycle_key(c) for c in cur.get("cycles", [])}
    by_key = {_cycle_key(c): c for c in cur.get("cycles", [])}
    by_key_b = {_cycle_key(c): c for c in base.get("cycles", [])}
    for k in cset - bset:
        c = by_key[k]
        items.append({"kind": "new_cycle", "risk": "high",
                      "detail": f"new {c['level']} cycle: {', '.join(c['members'])}"})
    for k in bset - cset:
        c = by_key_b[k]
        items.append({"kind": "resolved_cycle", "risk": "info",
                      "detail": f"resolved {c['level']} cycle: {', '.join(c['members'])}"})

    # --- dependency surface: new edges (esp. to sensitive layers) and removed ones --------
    bedges = {tuple(e) for e in base.get("edges", [])}
    cedges = {tuple(e) for e in cur.get("edges", [])}
    for a, b in sorted(cedges - bedges):
        risk = "high" if match_any(b, sensitive) else "medium"
        items.append({"kind": "new_dependency", "risk": risk,
                      "detail": f"new dependency: {a} → {b}"})
    for a, b in sorted(bedges - cedges):
        items.append({"kind": "removed_dependency", "risk": "info",
                      "detail": f"removed dependency: {a} → {b}"})

    # --- coupling/stability deltas per component ------------------------------------------
    for comp in sorted(set(bcomp) | set(ccomp)):
        mb, mc = bcomp.get(comp), ccomp.get(comp)
        if mb is None:
            items.append({"kind": "new_component", "risk": "low",
                          "detail": f"new component {comp} (Ce={mc['ce']}, Ca={mc['ca']})"})
            continue
        if mc is None:
            items.append({"kind": "removed_component", "risk": "info",
                          "detail": f"removed component {comp}"})
            continue
        dce = mc["ce"] - mb["ce"]
        grew = dce >= ce_jump or (mb["ce"] and dce > 0 and dce / mb["ce"] >= ce_pct)
        if grew:
            pct = f", +{round(100 * dce / mb['ce'])}%" if mb["ce"] else ""
            items.append({"kind": "coupling_increase",
                          "risk": "high" if dce >= 2 * ce_jump else "medium",
                          "detail": f"{comp}: efferent coupling Ce {mb['ce']} → {mc['ce']} (+{dce}{pct})"})
        di = round(mc["instability"] - mb["instability"], 3)
        if abs(di) >= inst_swing:
            items.append({"kind": "instability_shift", "risk": "low",
                          "detail": f"{comp}: instability {mb['instability']} → {mc['instability']} ({di:+})"})

    items.sort(key=lambda i: (-RISK_RANK.get(i["risk"], 0), i["kind"], i["detail"]))
    return {"items": items,
            "base_components": len(bcomp), "cur_components": len(ccomp),
            "new_edges": len(cedges - bedges), "removed_edges": len(bedges - cedges),
            "new_cycles": len(cset - bset), "resolved_cycles": len(bset - cset)}


def gate(d: dict, level: str = "high") -> tuple:
    """(passed, blocking): blocking = drift items at/above `level`. A PR gate typically blocks
    on `high` (new cycle / new sensitive dependency / coupling spike) and lets the rest through."""
    floor = RISK_RANK[level]
    blocking = [i for i in d["items"] if RISK_RANK.get(i["risk"], 0) >= floor]
    return (not blocking, blocking)


def counts(d: dict) -> dict:
    """Items bucketed by risk — for the report header."""
    out = {r: 0 for r in RISK_RANK}
    for i in d["items"]:
        out[i["risk"]] = out.get(i["risk"], 0) + 1
    return out
