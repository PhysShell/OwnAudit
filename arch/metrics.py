"""Coupling / stability metrics over the dependency graph — Martin's package metrics
(Own.NET Auditor docs/own-net-auditor.md §3, phase 3).

Graph-only today: afferent coupling Ca, efferent coupling Ce, and Instability I = Ce/(Ca+Ce)
per component (namespace or assembly). Forward-wired for the next two metrics so they cost no
refactor when the extractor grows:

  * **Abstractness A** and **Distance from the main sequence D = |A + I − 1|** are computed the
    moment graph nodes start carrying an `is_abstract` flag. Until then they stay `None` — the
    feature is dormant, callers and rules don't change.
  * **Cohesion (LCOM)** is deliberately NOT here: it needs a member-level (method↔field)
    access graph, a separate contract extension. This module stays type-/component-level.

`component_metrics()` is the single extension point and the thing phase-4 drift will diff.
"""
from __future__ import annotations

import collections


def _component_of(g, key: str) -> dict:
    """Internal node id -> its component (namespace/assembly). External nodes are excluded —
    coupling/stability is about the components we own; framework coupling is a layering concern."""
    return {nid: (g.node(nid).get(key) or "(none)") for nid in g.nodes if g._internal(nid)}


def component_metrics(g, key: str = "namespace") -> dict:
    """component -> {types, ca, ce, instability, abstractness, distance}.

    Ca/Ce are class-counted (Martin): Ce(P) = distinct classes OUTSIDE P that classes in P
    depend on; Ca(P) = distinct classes outside P that depend on classes in P. Only
    internal↔internal edges count. abstractness/distance are None unless nodes carry
    `is_abstract`."""
    comp_of = _component_of(g, key)
    comps = set(comp_of.values())

    ce_targets = collections.defaultdict(set)   # comp -> external classes it depends on
    ca_sources = collections.defaultdict(set)   # comp -> external classes depending on it
    for e in g.unique_edges():
        a, b = e.get("from"), e.get("to")
        if a not in comp_of or b not in comp_of:    # both endpoints must be internal (ours)
            continue
        ca_, cb_ = comp_of[a], comp_of[b]
        if ca_ == cb_:
            continue
        ce_targets[ca_].add(b)
        ca_sources[cb_].add(a)

    # Abstractness only if the contract actually carries it (graceful degradation).
    has_abs = any("is_abstract" in g.node(nid) for nid in comp_of)
    abs_count, tot_count = collections.Counter(), collections.Counter()
    for nid, c in comp_of.items():
        tot_count[c] += 1
        if g.node(nid).get("is_abstract"):
            abs_count[c] += 1

    out = {}
    for c in comps:
        ce, ca = len(ce_targets[c]), len(ca_sources[c])
        inst = ce / (ce + ca) if (ce + ca) else 0.0
        a = (abs_count[c] / tot_count[c]) if (has_abs and tot_count[c]) else None
        d = abs(a + inst - 1) if a is not None else None
        out[c] = {"types": tot_count[c], "ca": ca, "ce": ce,
                  "instability": round(inst, 3),
                  "abstractness": (round(a, 3) if a is not None else None),
                  "distance": (round(d, 3) if d is not None else None)}
    return out
