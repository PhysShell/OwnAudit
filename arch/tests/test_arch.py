"""Architecture engine tests (docs/own-net-auditor.md phase 3). Bare python3 or pytest:

    PYTHONPATH=. python3 arch/tests/test_arch.py

Proves: SCC cycle detection at type/namespace/assembly level (iterative, deep-safe),
layering violations only fire from internal sources, the god-class composite needs several
signals, and findings come out in the findings.json shape the SARIF/diff tooling consumes.
-O-safe (explicit raises).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from arch import cli                                                       # noqa: E402
from arch import drift_cli                                                # noqa: E402
from arch.graph import Graph, _scc, match_any                             # noqa: E402
from arch.metrics import component_metrics                                # noqa: E402
from arch import drift as DR                                              # noqa: E402
from arch import rules as R                                               # noqa: E402


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _t(tid, ns, asm="A", name=None, internal=True, file="x.cs", line=1, metrics=None):
    return {"id": tid, "kind": "type", "name": name or tid, "namespace": ns,
            "assembly": asm, "internal": internal, "loc": {"file": file, "line": line},
            "metrics": metrics or {}}


def _g(nodes, edges):
    return Graph({"schema": "ownAudit/arch-graph/v1", "nodes": nodes,
                  "edges": [{"from": a, "to": b, "kind": "depends"} for a, b in edges]})


# ---- cycle detection -------------------------------------------------------

def test_scc_finds_simple_cycle():
    comps = _scc({"a": ["b"], "b": ["c"], "c": ["a"], "d": []})
    big = [sorted(c) for c in comps if len(c) > 1]
    _expect(big == [["a", "b", "c"]], comps)


def test_scc_iterative_deep_no_recursion():
    # a long chain a0->a1->...->a4999->a0 : recursion would blow the stack here
    n = 5000
    adj = {f"a{i}": [f"a{(i + 1) % n}"] for i in range(n)}
    comps = _scc(adj)
    big = [c for c in comps if len(c) > 1]
    _expect(len(big) == 1 and len(big[0]) == n, len(big))


def test_type_cycle_detected_and_anchored():
    g = _g([_t("T:X", "Sts.A", name="X", file="X.cs", line=3),
            _t("T:Y", "Sts.A", name="Y", file="Y.cs", line=7)],
           [("T:X", "T:Y"), ("T:Y", "T:X")])
    f = R.check_cycles(g, {"type": True})
    _expect(len(f) == 1 and f[0]["rule"] == "ARCH-CYCLE-TYPE", f)
    _expect(f[0]["path"] == "X.cs" and f[0]["tool"] == "own-arch", f[0])      # anchored at lexed-first
    _expect("X" in f[0]["message"] and "Y" in f[0]["message"], f[0]["message"])


def test_self_loop_is_not_a_cycle():
    # a type referencing itself (recursive method, self field) is normal, not a smell
    g = _g([_t("T:S", "Sts.A")], [("T:S", "T:S")])
    _expect(R.check_cycles(g, {"type": True}) == [], "self-loop must not flag")


def test_namespace_cycle_independent_of_type_cycle():
    # X(ns A) -> Y(ns B) -> Z(ns A): no type cycle, but A <-> B at namespace level
    g = _g([_t("T:X", "Sts.A"), _t("T:Y", "Sts.B"), _t("T:Z", "Sts.A")],
           [("T:X", "T:Y"), ("T:Y", "T:Z")])
    _expect(R.check_cycles(g, {"type": True}) == [], "no type cycle")
    nsc = R.check_cycles(g, {"namespace": True})
    _expect(len(nsc) == 1 and nsc[0]["rule"] == "ARCH-CYCLE-NS", nsc)


def test_assembly_cycle():
    g = _g([_t("T:X", "Sts.A", asm="P"), _t("T:Y", "Sts.B", asm="Q")],
           [("T:X", "T:Y"), ("T:Y", "T:X")])
    asc = R.check_cycles(g, {"assembly": True})
    _expect(len(asc) == 1 and asc[0]["rule"] == "ARCH-CYCLE-ASM", asc)


# ---- layering --------------------------------------------------------------

LAYERS = [
    {"id": "ARCH-UI-SQL", "message": "UI->SQL",
     "from": ["Sts.UI.*"], "to": ["*.Data.Sql*", "System.Data.SqlClient*"]},
    {"id": "ARCH-DOMAIN-WPF", "message": "Domain->WPF",
     "from": ["Sts.Domain.*"], "to": ["System.Windows.*"]},
]


def test_layering_ui_to_sql_flagged():
    g = _g([_t("T:V", "Sts.UI.Views", name="OrdersView"),
            _t("T:Repo", "Sts.Data.SqlRepo", name="OrderRepo")],
           [("T:V", "T:Repo")])
    f = R.check_layering(g, LAYERS)
    _expect(len(f) == 1 and f[0]["rule"] == "ARCH-UI-SQL", f)
    _expect(f[0]["resource"] == "OrdersView", f[0])


def test_layering_matches_external_framework_target():
    # domain type depending on an EXTERNAL System.Windows.* type is still a violation
    g = _g([_t("T:D", "Sts.Domain.Orders", name="Order"),
            _t("T:W", "System.Windows", name="DependencyObject", internal=False)],
           [("T:D", "T:W")])
    f = R.check_layering(g, LAYERS)
    _expect(len(f) == 1 and f[0]["rule"] == "ARCH-DOMAIN-WPF", f)


def test_layering_source_must_be_internal():
    # if the SOURCE is third-party we cannot fix it -> never flagged
    g = _g([_t("T:Ext", "Sts.UI.Vendor", name="VendorGrid", internal=False),
            _t("T:Repo", "Sts.Data.SqlRepo", name="OrderRepo")],
           [("T:Ext", "T:Repo")])
    _expect(R.check_layering(g, LAYERS) == [], "external source must not flag")


def test_layering_clean_direction_not_flagged():
    # Data -> UI is not one of our forbidden directions
    g = _g([_t("T:Repo", "Sts.Data.SqlRepo"), _t("T:V", "Sts.UI.Views")],
           [("T:Repo", "T:V")])
    _expect(R.check_layering(g, LAYERS) == [], "clean direction")


def test_layering_dedupes_duplicate_edges():
    # the same UI->SQL dependency seen via several members yields ONE finding, not three
    g = _g([_t("T:V", "Sts.UI.Views", name="OrdersView"),
            _t("T:Repo", "Sts.Data.SqlRepo", name="OrderRepo")],
           [("T:V", "T:Repo"), ("T:V", "T:Repo"), ("T:V", "T:Repo")])
    _expect(len(R.check_layering(g, LAYERS)) == 1, "duplicate edges must collapse")


# ---- god class -------------------------------------------------------------

GOD = {"id": "ARCH-GOD-CLASS", "min_signals": 2,
       "methods": 40, "fields": 25, "loc": 1000, "deps_out": 30}


def test_god_class_needs_multiple_signals():
    # one axis over threshold -> not a god class
    g = _g([_t("T:Big", "Sts.A", name="Big", metrics={"methods": 99, "fields": 1, "loc": 10})], [])
    _expect(R.check_god_class(g, GOD) == [], "single signal not enough")


def test_god_class_flags_multi_axis():
    g = _g([_t("T:God", "Sts.A", name="GodService",
               metrics={"methods": 80, "fields": 40, "loc": 50})], [])
    f = R.check_god_class(g, GOD)
    _expect(len(f) == 1 and f[0]["rule"] == "ARCH-GOD-CLASS", f)
    _expect("GodService" in f[0]["message"], f[0]["message"])


def test_god_class_deps_out_from_graph():
    # methods over threshold + fan-out computed from edges (not metrics) = 2 signals
    edges = [("T:Hub", f"T:n{i}") for i in range(31)]
    nodes = [_t("T:Hub", "Sts.A", name="Hub", metrics={"methods": 50})]
    nodes += [_t(f"T:n{i}", "Sts.B") for i in range(31)]
    g = _g(nodes, edges)
    f = R.check_god_class(g, GOD)
    _expect(len(f) == 1 and "outgoing deps 31" in f[0]["message"], f)


def test_god_class_fan_out_counts_external_deps():
    # a hub leaning on 31 EXTERNAL framework types must still trip the fan-out signal
    # (regression: deps_out used to read internal-only adjacency and miss this).
    edges = [("T:Hub", f"T:ext{i}") for i in range(31)]
    nodes = [_t("T:Hub", "Sts.A", name="Hub", metrics={"methods": 50})]
    nodes += [_t(f"T:ext{i}", "System.Windows", internal=False) for i in range(31)]
    g = _g(nodes, edges)
    _expect(g.fan_out("T:Hub") == 31 and len(g.deps_out("T:Hub")) == 0, "external fan-out")
    f = R.check_god_class(g, GOD)
    _expect(len(f) == 1 and "outgoing deps 31" in f[0]["message"], f)


def test_fan_out_dedupes_repeated_edges():
    g = _g([_t("T:A", "Sts.A"), _t("T:B", "Sts.B")],
           [("T:A", "T:B"), ("T:A", "T:B")])
    _expect(g.fan_out("T:A") == 1 and len(g.unique_edges()) == 1, "dedup fan-out")


# ---- helpers / shape -------------------------------------------------------

def test_match_any_case_sensitive():
    _expect(match_any("Sts.UI.Views", ["Sts.UI.*"]), "should match")
    _expect(not match_any("sts.ui.views", ["Sts.UI.*"]), "case sensitive")
    _expect(not match_any("X", []), "no patterns")


def test_findings_have_canonical_shape():
    g = _g([_t("T:X", "Sts.A", name="X"), _t("T:Y", "Sts.A", name="Y")],
           [("T:X", "T:Y"), ("T:Y", "T:X")])
    f = R.check_cycles(g, {"type": True})[0]
    for k in ("tool", "rule", "category_name", "resource", "path", "line", "message", "suppressed"):
        _expect(k in f, f"missing {k}")
    _expect(f["category_name"] == "architecture" and f["suppressed"] is False, f)


def test_run_combines_all_kinds():
    rules = {"layers": LAYERS, "cycles": {"type": True}, "god_class": GOD}
    g = _g([_t("T:V", "Sts.UI.Views", name="V"), _t("T:Repo", "Sts.Data.SqlRepo", name="Repo"),
            _t("T:X", "Sts.A", name="X"), _t("T:Y", "Sts.A", name="Y")],
           [("T:V", "T:Repo"), ("T:X", "T:Y"), ("T:Y", "T:X")])
    f = R.run(g, rules)
    rule_ids = {x["rule"] for x in f}
    _expect("ARCH-UI-SQL" in rule_ids and "ARCH-CYCLE-TYPE" in rule_ids, rule_ids)


def test_shipped_rules_json_loads():
    rules = R.load_rules()           # arch/rules.json must be valid and have the 3 kinds
    _expect("layers" in rules and "cycles" in rules and "god_class" in rules, rules.keys())


def test_cli_writes_findings_and_report():
    d = tempfile.mkdtemp(prefix="arch-")
    try:
        gp = os.path.join(d, "graph.json")
        with open(gp, "w", encoding="utf-8") as fh:
            json.dump({"schema": "ownAudit/arch-graph/v1",
                       "nodes": [_t("T:X", "Sts.A", name="X"), _t("T:Y", "Sts.A", name="Y")],
                       "edges": [{"from": "T:X", "to": "T:Y"}, {"from": "T:Y", "to": "T:X"}]}, fh)
        out = os.path.join(d, "out")
        rc = cli.main(["--graph", gp, "--out-dir", out])
        _expect(rc == 0, rc)
        j = json.load(open(os.path.join(out, "arch-findings.json"), encoding="utf-8"))
        _expect(len(j["findings"]) == 1 and j["findings"][0]["rule"] == "ARCH-CYCLE-TYPE", j)
        _expect(os.path.exists(os.path.join(out, "arch-report.md")), "report written")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cli_missing_graph_exits_2():
    # fresh dir + a child path we never create -> the SystemExit(2) path is always exercised
    d = tempfile.mkdtemp(prefix="arch-")
    raised = None
    try:
        cli.main(["--graph", os.path.join(d, "does-not-exist.json")])
    except SystemExit as e:
        raised = e.code
    finally:
        shutil.rmtree(d, ignore_errors=True)
    _expect(raised == 2, raised)


def test_cli_rejects_directory_graph():
    # a directory passed as --graph must hit the same clean exit 2, not raise IsADirectoryError
    d = tempfile.mkdtemp(prefix="arch-")
    raised = None
    try:
        cli.main(["--graph", d])
    except SystemExit as e:
        raised = e.code
    finally:
        shutil.rmtree(d, ignore_errors=True)
    _expect(raised == 2, raised)


def test_bad_schema_rejected():
    raised = None
    try:
        Graph({"schema": "ownAudit/arch-graph/v999", "nodes": [], "edges": []})
    except ValueError as e:
        raised = str(e)
    _expect(raised is not None and "schema" in raised, raised)


def test_malformed_graph_rejected():
    # nodes/edges must be lists, and every node must carry an id
    for bad in ({"schema": "ownAudit/arch-graph/v1", "nodes": {}, "edges": []},
                {"schema": "ownAudit/arch-graph/v1", "nodes": [{"name": "no-id"}], "edges": []}):
        raised = None
        try:
            Graph(bad)
        except ValueError as e:
            raised = e
        _expect(raised is not None, f"expected ValueError for {bad}")


# ---- coupling / stability metrics ------------------------------------------

def test_instability_pure_source_and_sink():
    # A(ns P) -> B(ns Q): P only depends (I=1), Q only depended-upon (I=0)
    g = _g([_t("T:A", "P"), _t("T:B", "Q")], [("T:A", "T:B")])
    m = component_metrics(g, "namespace")
    _expect(m["P"]["instability"] == 1.0 and m["P"]["ce"] == 1 and m["P"]["ca"] == 0, m["P"])
    _expect(m["Q"]["instability"] == 0.0 and m["Q"]["ca"] == 1 and m["Q"]["ce"] == 0, m["Q"])


def test_metrics_ignore_external_edges():
    ext = {"id": "T:Ext", "name": "Ext", "namespace": "System", "assembly": "S", "internal": False}
    g = Graph({"schema": "ownAudit/arch-graph/v1", "nodes": [_t("T:A", "P"), ext],
               "edges": [{"from": "T:A", "to": "T:Ext"}]})
    m = component_metrics(g, "namespace")
    _expect(m["P"]["ce"] == 0, m["P"])           # external dep doesn't count toward Ce
    _expect("System" not in m, list(m))          # external component not tracked


def test_abstractness_dormant_without_flag_then_lights_up():
    g = _g([_t("T:A", "P"), _t("T:B", "P")], [])
    _expect(component_metrics(g, "namespace")["P"]["abstractness"] is None, "dormant")
    # add the flag -> A and D populate with no code change
    g2 = _g([dict(_t("T:A", "P"), is_abstract=True), dict(_t("T:B", "P"), is_abstract=False)], [])
    mp = component_metrics(g2, "namespace")["P"]
    _expect(mp["abstractness"] == 0.5 and mp["distance"] is not None, mp)


def _sdp_graph():
    # stable comp S (3 depend on it, it depends on 1) vs unstable comp U (depends on 3)
    nodes = [_t("T:S0", "Sts.S"), _t("T:U0", "Sts.U")]
    nodes += [_t(f"T:A{i}", "Sts.App") for i in range(3)]
    nodes += [_t(f"T:L{i}", "Sts.Lib") for i in range(3)]
    edges = [(f"T:A{i}", "T:S0") for i in range(3)]
    edges += [("T:S0", "T:U0")]                             # stable S -> unstable U: violation
    edges += [("T:U0", f"T:L{i}") for i in range(3)]
    return _g(nodes, edges)


def test_sdp_flags_stable_depending_on_unstable():
    cfg = {"level": "namespace", "sdp": {"id": "ARCH-SDP", "min_gap": 0.3, "min_ce": 1}}
    sdp = [x for x in R.check_coupling(_sdp_graph(), cfg) if x["rule"] == "ARCH-SDP"]
    _expect(len(sdp) == 1 and sdp[0]["resource"] == "Sts.S", sdp)


def test_sdp_silent_on_clean_layering():
    # downward deps only: high-I depends on low-I -> SDP satisfied -> nothing
    g = _g([_t("T:V", "UI"), _t("T:D", "Data")], [("T:V", "T:D")])
    cfg = {"level": "namespace", "sdp": {"id": "ARCH-SDP", "min_gap": 0.3, "min_ce": 1}}
    _expect([x for x in R.check_coupling(g, cfg) if x["rule"] == "ARCH-SDP"] == [], "clean")


def test_unstable_hub_flagged():
    nodes = [_t("T:H", "Sts.Hub"), _t("T:X0", "Sts.X"), _t("T:X1", "Sts.X"),
             _t("T:Y0", "Sts.Y"), _t("T:Y1", "Sts.Y")]
    edges = [("T:X0", "T:H"), ("T:X1", "T:H"), ("T:H", "T:Y0"), ("T:H", "T:Y1")]
    cfg = {"level": "namespace", "unstable_hub": {"id": "ARCH-UNSTABLE-HUB", "min_ca": 2, "min_ce": 2}}
    f = [x for x in R.check_coupling(_g(nodes, edges), cfg) if x["rule"] == "ARCH-UNSTABLE-HUB"]
    _expect(len(f) == 1 and f[0]["resource"] == "Sts.Hub", f)


def test_coupling_disabled_without_config():
    _expect(R.check_coupling(_sdp_graph(), {}) == [], "no config -> no findings")


# ---- architecture drift (phase 4) ------------------------------------------

DRIFT_CFG = {"level": "namespace", "ce_jump": 5, "ce_pct": 0.25, "inst_swing": 0.2,
             "sensitive_targets": ["System.Data.SqlClient*", "*.Data.Sql*"]}


def _base_graph():
    # clean: UI -> Domain -> Data, no cycles, no SQL leak
    return _g([_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data")],
              [("T:V", "T:D"), ("T:D", "T:R")])


def test_drift_identical_is_empty():
    g = _base_graph()
    d = DR.diff(DR.snapshot(g), DR.snapshot(g), DRIFT_CFG)
    _expect(d["items"] == [] and d["new_cycles"] == 0 and d["new_edges"] == 0, d)


def test_drift_new_cycle_is_high():
    # same namespace -> a mutual dep is exactly ONE (type) cycle, not also a namespace cycle
    base = DR.snapshot(_g([_t("T:A", "Sts.Core", name="A"), _t("T:B", "Sts.Core", name="B")],
                          [("T:A", "T:B")]))
    cur = DR.snapshot(_g([_t("T:A", "Sts.Core", name="A"), _t("T:B", "Sts.Core", name="B")],
                         [("T:A", "T:B"), ("T:B", "T:A")]))
    d = DR.diff(base, cur, DRIFT_CFG)
    high = [i for i in d["items"] if i["risk"] == "high" and i["kind"] == "new_cycle"]
    _expect(len(high) == 1 and d["new_cycles"] == 1, d["items"])


def test_drift_new_sql_dependency_is_high():
    base = DR.snapshot(_base_graph())
    ext = {"id": "T:Sql", "name": "SqlConnection", "namespace": "System.Data.SqlClient",
           "assembly": "System.Data", "internal": False}
    cur = DR.snapshot(Graph({"schema": "ownAudit/arch-graph/v1",
                             "nodes": [_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"),
                                       _t("T:R", "Sts.Data"), ext],
                             "edges": [{"from": "T:V", "to": "T:D"}, {"from": "T:D", "to": "T:R"},
                                       {"from": "T:V", "to": "T:Sql"}]}))
    d = DR.diff(base, cur, DRIFT_CFG)
    sql = [i for i in d["items"] if i["kind"] == "new_dependency" and i["risk"] == "high"]
    _expect(len(sql) == 1 and "System.Data.SqlClient" in sql[0]["detail"], d["items"])


def test_drift_plain_new_dependency_is_medium():
    base = DR.snapshot(_base_graph())
    cur = DR.snapshot(_g([_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data"),
                          _t("T:L", "Sts.Logging")],
                         [("T:V", "T:D"), ("T:D", "T:R"), ("T:D", "T:L")]))
    d = DR.diff(base, cur, DRIFT_CFG)
    med = [i for i in d["items"] if i["kind"] == "new_dependency" and i["risk"] == "medium"]
    _expect(any("Sts.Logging" in i["detail"] for i in med), d["items"])


def test_drift_coupling_increase_flagged():
    base = DR.snapshot(_g([_t("T:H", "Sts.Hub"), _t("T:A", "Sts.A")], [("T:H", "T:A")]))
    # Hub now depends on 7 more components -> Ce jumps well past ce_jump
    nodes = [_t("T:H", "Sts.Hub"), _t("T:A", "Sts.A")] + [_t(f"T:N{i}", f"Sts.N{i}") for i in range(7)]
    edges = [("T:H", "T:A")] + [("T:H", f"T:N{i}") for i in range(7)]
    cur = DR.snapshot(_g(nodes, edges))
    d = DR.diff(base, cur, DRIFT_CFG)
    ci = [i for i in d["items"] if i["kind"] == "coupling_increase" and "Sts.Hub" in i["detail"]]
    _expect(len(ci) == 1 and ci[0]["risk"] in ("medium", "high"), d["items"])


def test_drift_resolved_cycle_is_info_not_blocking():
    # baseline HAS a (type) cycle, current fixed it -> info, never blocks the gate
    base = DR.snapshot(_g([_t("T:A", "Sts.Core", name="A"), _t("T:B", "Sts.Core", name="B")],
                          [("T:A", "T:B"), ("T:B", "T:A")]))
    cur = DR.snapshot(_g([_t("T:A", "Sts.Core", name="A"), _t("T:B", "Sts.Core", name="B")],
                         [("T:A", "T:B")]))
    d = DR.diff(base, cur, DRIFT_CFG)
    _expect(d["resolved_cycles"] == 1, d)
    passed, blocking = DR.gate(d, "high")
    _expect(passed and not blocking, blocking)


def test_drift_gate_blocks_high_only():
    base = DR.snapshot(_base_graph())
    cur = DR.snapshot(_g([_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain", name="D"),
                          _t("T:R", "Sts.Data", name="R")],
                         [("T:V", "T:D"), ("T:D", "T:R"), ("T:R", "T:D")]))   # new cycle = high
    d = DR.diff(base, cur, DRIFT_CFG)
    _expect(not DR.gate(d, "high")[0], "high blocks")
    # a medium-only drift (plain new dep) passes a high gate
    cur2 = DR.snapshot(_g([_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data"),
                           _t("T:L", "Sts.Log")], [("T:V", "T:D"), ("T:D", "T:R"), ("T:D", "T:L")]))
    d2 = DR.diff(base, cur2, DRIFT_CFG)
    _expect(DR.gate(d2, "high")[0] and not DR.gate(d2, "medium")[0], d2["items"])


def test_drift_cycle_key_uses_full_identity():
    # two cycles sharing the SAME short names (Service/Repository) in DIFFERENT namespaces
    # must be distinct — short-name keys would collapse them and mask the new one.
    def cyc(ns_list):
        nodes, edges = [], []
        for ns in ns_list:
            nodes += [_t(f"T:{ns}.Service", ns, name="Service"),
                      _t(f"T:{ns}.Repo", ns, name="Repository")]
            edges += [(f"T:{ns}.Service", f"T:{ns}.Repo"), (f"T:{ns}.Repo", f"T:{ns}.Service")]
        return DR.snapshot(_g(nodes, edges))
    base = cyc(["Sts.A"])
    cur = cyc(["Sts.A", "Sts.B"])            # adds an identically-named cycle in Sts.B
    d = DR.diff(base, cur, DRIFT_CFG)
    new_type = [i for i in d["items"] if i["kind"] == "new_cycle" and "type" in i["detail"]]
    _expect(len(new_type) == 1, d["items"])


def test_drift_level_mismatch_rejected():
    snap_ns = DR.snapshot(_base_graph(), "namespace")
    raised = None
    try:
        DR.as_snapshot(snap_ns, "assembly")
    except ValueError as e:
        raised = str(e)
    _expect(raised is not None and "level" in raised, raised)
    # same level is fine
    _expect(DR.as_snapshot(snap_ns, "namespace") is snap_ns, "same level passes through")


def test_drift_as_snapshot_accepts_raw_graph():
    # a raw graph.json dict (not a pre-made snapshot) is converted on the fly
    raw = {"schema": "ownAudit/arch-graph/v1",
           "nodes": [_t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data")],
           "edges": [{"from": "T:D", "to": "T:R"}]}
    snap = DR.as_snapshot(raw)
    _expect(snap["schema"] == DR.SCHEMA and "Sts.Domain" in snap["components"], snap)


def _write_graph(path, nodes, edges):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": "ownAudit/arch-graph/v1", "nodes": nodes,
                   "edges": [{"from": a, "to": b} for a, b in edges]}, fh)


def test_drift_cli_snapshot_then_gate():
    d = tempfile.mkdtemp(prefix="drift-")
    try:
        base_g = os.path.join(d, "base.json")
        _write_graph(base_g, [_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data")],
                     [("T:V", "T:D"), ("T:D", "T:R")])
        snap = os.path.join(d, "snap.json")
        out = os.path.join(d, "out")
        _expect(drift_cli.main(["--graph", base_g, "--save-snapshot", "--snapshot", snap]) == 0, "save")
        _expect(os.path.exists(snap), "snapshot written")
        # same graph vs snapshot -> clean, exit 0 even with a high gate
        _expect(drift_cli.main(["--graph", base_g, "--baseline", snap, "--out-dir", out,
                                "--gate-level", "high"]) == 0, "clean")
        # introduce a new cycle -> high -> exit 2
        cur_g = os.path.join(d, "cur.json")
        _write_graph(cur_g, [_t("T:V", "Sts.UI"), _t("T:D", "Sts.Domain"), _t("T:R", "Sts.Data")],
                     [("T:V", "T:D"), ("T:D", "T:R"), ("T:R", "T:D")])
        rc = drift_cli.main(["--graph", cur_g, "--baseline", snap, "--out-dir", out, "--gate-level", "high"])
        _expect(rc == 2, rc)
        j = json.load(open(os.path.join(out, "drift.json"), encoding="utf-8"))
        _expect(j["new_cycles"] >= 1, j)         # R<->D is a type cycle (and a namespace cycle)
        _expect(os.path.exists(os.path.join(out, "drift.md")), "drift.md written")
        # ...but without a gate level it's report-only -> exit 0
        _expect(drift_cli.main(["--graph", cur_g, "--baseline", snap, "--out-dir", out]) == 0, "report-only")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- bare-python runner ----------------------------------------------------

def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
