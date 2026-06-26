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
from arch.graph import Graph, _scc, match_any                             # noqa: E402
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
    raised = None
    try:
        cli.main(["--graph", os.path.join(tempfile.gettempdir(), "ownaudit-no-graph.json")])
    except SystemExit as e:
        raised = e.code
    _expect(raised == 2, raised)


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
