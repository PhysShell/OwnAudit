"""Architecture graph model + cycle detection (Own.NET Auditor docs/own-net-auditor.md §3, phase 3).

Consumes a `graph.json` emitted on the Windows stand by the Roslyn symbol-graph extractor
(schema in docs/arch-graph.md) and answers the structural questions the rules engine needs:
who-depends-on-whom, and where the dependency graph has cycles — at the type, namespace, and
assembly level. Pure stdlib, no .NET, so it runs and is tested in CI just like the SARIF/diff
tooling; the heavy symbol resolution stays on the stand.

Cycles are found with an iterative Tarjan SCC (no recursion — a real STS namespace graph is
deep enough to blow the interpreter's stack), and the >1-member SCCs ARE the cycles.
"""
from __future__ import annotations

import fnmatch


# Graph schemas this engine understands. The loader fails fast on anything else so a
# changed/old extractor surfaces at the boundary instead of as silent false findings.
SUPPORTED_SCHEMAS = frozenset({"ownAudit/arch-graph/v1"})


def match_any(name: str, patterns) -> bool:
    """True if `name` matches any glob pattern (case-sensitive, fnmatchcase). Used by the
    layering rules — `Sts.UI.*`, `*.Data.Sql*` etc. — so namespaces read like the source."""
    return any(fnmatch.fnmatchcase(name or "", p) for p in (patterns or ()))


def _scc(adj: dict) -> list:
    """Tarjan's strongly-connected-components, iterative. `adj` is node -> iterable of
    successors. Returns a list of components (each a list of nodes). Single-node components
    are included; the caller decides what counts as a cycle (an SCC of size >1, or a node
    with a self-loop)."""
    index = {}            # node -> dfs index
    low = {}              # node -> lowlink
    on_stack = set()
    stack = []            # the SCC working stack
    out = []
    counter = 0

    for root in adj:
        if root in index:
            continue
        # work item: (node, iterator over its successors, started?)
        work = [(root, iter(adj.get(root, ())))]
        while work:
            node, it = work[-1]
            if node not in index:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            advanced = False
            for succ in it:
                if succ not in index:
                    work.append((succ, iter(adj.get(succ, ()))))
                    advanced = True
                    break
                if succ in on_stack:
                    low[node] = min(low[node], index[succ])
            if advanced:
                continue
            # all successors processed: settle this node
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(comp)
            work.pop()
            if work:                                  # propagate lowlink to the parent
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out


class Graph:
    """Dependency graph over Roslyn type symbols. Only INTERNAL nodes (types defined in the
    audited solution) participate in cycle/layer analysis — edges to framework/third-party
    types are kept for context but never flagged."""

    def __init__(self, data: dict):
        # Validate the contract before trusting the data — a drifted/old graph should stop
        # here with a clear error, not produce confident garbage (docs/arch-graph.md).
        self.schema = data.get("schema", "")
        if self.schema not in SUPPORTED_SCHEMAS:
            raise ValueError(f"unsupported graph schema {self.schema!r}; expected one of "
                             f"{sorted(SUPPORTED_SCHEMAS)} (see docs/arch-graph.md)")
        nodes, edges = data.get("nodes"), data.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("graph.json must have list-valued 'nodes' and 'edges'")
        if any(not isinstance(n, dict) or "id" not in n for n in nodes):
            raise ValueError("every graph node must be an object with an 'id'")
        self.nodes = {n["id"]: n for n in nodes}
        self.edges = list(edges)                      # raw, as given

        # Collapse duplicate edges and drop self-loops once (the graph contract: a type
        # referenced by several members yields one edge). `_out` is the FULL outgoing
        # adjacency from each source to ANY target, internal or external — what god-class
        # fan-out and layering consume. `_adj` is the internal→internal subset that cycle
        # detection runs on (external targets can't be part of a cycle we own).
        self._out: dict = {}
        self._unique_edges: list = []
        seen = set()
        for e in self.edges:
            a, b = e.get("from"), e.get("to")
            if a is None or b is None or a == b or (a, b) in seen:
                continue
            seen.add((a, b))
            self._unique_edges.append(e)
            self._out.setdefault(a, set()).add(b)

        self._adj: dict = {nid: set() for nid in self.nodes if self._internal(nid)}
        for a, targets in self._out.items():
            if a in self._adj:
                self._adj[a].update(b for b in targets if b in self._adj)

    @classmethod
    def load(cls, path: str) -> "Graph":
        """Build a Graph from a graph.json file (schema: docs/arch-graph.md)."""
        import json
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def _internal(self, nid: str) -> bool:
        """Is this node defined in the audited solution (ours to flag)? A bare node with no
        `internal` key defaults to True."""
        n = self.nodes.get(nid) or {}
        return bool(n.get("internal", True))      # default true: a bare node is ours

    def node(self, nid: str) -> dict:
        """The raw node dict for an id, or {} if unknown."""
        return self.nodes.get(nid, {})

    # -- attribute accessors (graph.json node fields) -----------------------------
    def name(self, nid: str) -> str:
        """Short type name (falls back to the id)."""
        return self.nodes.get(nid, {}).get("name", nid)

    def namespace(self, nid: str) -> str:
        """Declaring namespace ("" if unknown)."""
        return self.nodes.get(nid, {}).get("namespace", "")

    def assembly(self, nid: str) -> str:
        """Declaring assembly ("" if unknown)."""
        return self.nodes.get(nid, {}).get("assembly", "")

    def type_ids(self) -> list:
        """Internal type node ids, in input order."""
        return [nid for nid in self.nodes if self._internal(nid)]

    def deps_out(self, nid: str) -> set:
        """Internal dependency targets (what cycle detection sees). For total coupling
        fan-out including framework/third-party targets, use fan_out()."""
        return self._adj.get(nid, set())

    def fan_out(self, nid: str) -> int:
        """Distinct outgoing dependencies, internal AND external, self excluded — the real
        coupling number. A type leaning on 30+ framework types still trips god-class here."""
        return len(self._out.get(nid, ()))

    def unique_edges(self) -> list:
        """Edges with duplicates collapsed and self-loops dropped (the graph contract)."""
        return self._unique_edges

    # -- cycle detection ----------------------------------------------------------
    def _cycles(self, adj: dict) -> list:
        """SCCs that are genuine cycles: components of size >1. Self-edges are dropped at
        construction (a type/namespace referencing itself is not an architectural smell), so
        a 1-member SCC is never a cycle here."""
        return [comp for comp in _scc(adj) if len(comp) > 1]

    def type_cycles(self) -> list:
        """Strongly-connected groups of types (mutual/recursive dependency)."""
        return self._cycles(self._adj)

    def _level_graph(self, key) -> tuple:
        """Collapse the type graph by a node attribute (`namespace`/`assembly`). Returns
        (adjacency over the grouped keys, group -> member type ids)."""
        members: dict = {}
        for nid in self._adj:
            g = self.nodes.get(nid, {}).get(key) or "(none)"
            members.setdefault(g, []).append(nid)
        adj: dict = {g: set() for g in members}
        for nid, succs in self._adj.items():
            ga = self.nodes.get(nid, {}).get(key) or "(none)"
            for s in succs:
                gb = self.nodes.get(s, {}).get(key) or "(none)"
                if ga != gb:
                    adj[ga].add(gb)
        return adj, members

    def namespace_cycles(self) -> list:
        adj, _ = self._level_graph("namespace")
        return self._cycles(adj)

    def assembly_cycles(self) -> list:
        adj, _ = self._level_graph("assembly")
        return self._cycles(adj)
