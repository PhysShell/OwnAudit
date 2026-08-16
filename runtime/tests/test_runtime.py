"""Runtime correlation tests (docs/own-net-auditor.md phase 5). Bare python3 or pytest:

    PYTHONPATH=. python3 runtime/tests/test_runtime.py

Proves the three-way split: a static leak finding + matching heap retention -> confirmed (with
a confidence that rises when a static-event delegate holds the instances), a static finding with
no retention -> static-only (suspect FP), retention with no static finding -> runtime-only
(blind spot). Noise-level excess is not confirmed. -O-safe (explicit raises).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from runtime import correlate as C                                        # noqa: E402
from runtime import cli                                                   # noqa: E402


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _sf(resource, cat="subscription-leak", rule="OWN001", event=None):
    # subscription findings carry the canonical own-check event identity so the
    # member-aware contract can match them against a static-event root; passing
    # event=None models a message with no parseable identity (never guessed).
    msg = (f"event '{event}' is subscribed but never unsubscribed"
           if event else "no matching unsubscribe")
    return {"tool": "own-check", "rule": rule, "category_name": cat, "resource": resource,
            "path": f"Broker/{resource}.cs", "line": 10, "message": msg}


def _retained(t, count, expected=1, bytes_=None, event_holder=None):
    rec = {"type": t, "count": count, "expected": expected}
    if bytes_ is not None:
        rec["bytes"] = bytes_
    if event_holder:
        rec["roots"] = [{"kind": "static-event", "holder": event_holder, "member": "Changed",
                         "via": "delegate"}]
    return rec


def _dump(*records, scenario="open/close window", iterations=10):
    return {"schema": "ownAudit/runtime/v1", "scenario": scenario, "iterations": iterations,
            "retained": list(records)}


CFG = {"leak_categories": ["subscription-leak", "idisposable-leak", "region-escape"],
       "default_expected": 1, "min_count": 2, "high_count": 10}


def test_confirmed_event_leak_is_high_and_rooted():
    static = [_sf("DocumentsViewModel", event="DocumentStore.Changed")]
    dump = _dump(_retained("DocumentsViewModel", 132, expected=1, bytes_=88080384,
                           event_holder="Sts.Broker.Documents.DocumentStore"))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)
    f = res["confirmed"][0]
    _expect(f["confidence"] == "high" and f["category_name"] == "runtime-confirmed-leak", f)
    _expect("DocumentStore.Changed" in f["message"] and "MB" in f["message"], f["message"])
    _expect(f["tool"] == "own-runtime" and f["retained"] == 132, f)


def test_confirmed_modest_retention_is_medium():
    # count 4 over expected 1 = excess 3 (>= min_count, < high_count), no event root -> medium
    static = [_sf("OrderService", cat="idisposable-leak", rule="CA2000")]
    res = C.correlate(static, _dump(_retained("OrderService", 4)), CFG)
    _expect(len(res["confirmed"]) == 1 and res["confirmed"][0]["confidence"] == "medium", res)


def test_rooted_event_small_growth_is_high():
    # held by a static event delegate and growing -> high even at small counts (classic leak)
    static = [_sf("PopupVm", event="Shell.Changed")]
    dump = _dump(_retained("PopupVm", 3, expected=1, event_holder="App.Shell"))
    _expect(C.correlate(static, dump, CFG)["confirmed"][0]["confidence"] == "high", "rooted->high")


def test_noise_excess_not_confirmed():
    # count 2 over expected 1 = excess 1 (< min_count) -> not confirmed, stays static-only
    static = [_sf("Widget")]
    res = C.correlate(static, _dump(_retained("Widget", 2)), CFG)
    _expect(not res["confirmed"] and len(res["static_only"]) == 1, res)


def test_static_only_when_no_retention():
    static = [_sf("CleanVm")]
    res = C.correlate(static, _dump(_retained("OtherType", 50)), CFG)
    _expect(not res["confirmed"] and res["static_only"][0]["resource"] == "CleanVm", res)


def test_runtime_only_blind_spot():
    # big retention for a type with NO static leak finding -> runtime-only
    res = C.correlate([_sf("KnownVm")],
                      _dump(_retained("KnownVm", 1), _retained("SurpriseVm", 40)), CFG)
    ro = res["runtime_only"]
    _expect(len(ro) == 1 and ro[0]["resource"] == "SurpriseVm", ro)
    _expect(ro[0]["category_name"] == "runtime-only-leak" and ro[0]["rule"] == "RUNTIME-UNPREDICTED", ro)


def test_matches_owner_type_from_path_not_resource():
    # real own-check shape: resource is a DESCRIPTION, the leaked type is the code-behind class.
    static = [{"tool": "own-check", "rule": "OWN001", "category_name": "subscription-leak",
               "resource": "subscription token", "path": "Broker/AmountWindow.xaml.cs", "line": 72,
               "message": "event 'GoodsStore.Changed' subscribed but never unsubscribed"}]
    dump = _dump(_retained("Sts.Broker.AmountWindow", 64, expected=0,
                           event_holder="Sts.Broker.GoodsStore"))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1 and not res["runtime_only"], res)
    f = res["confirmed"][0]
    _expect(f["resource"] == "Sts.Broker.AmountWindow" and f["confidence"] == "high", f)
    _expect(f["static_resource"] == "subscription token" and f["path"].endswith("AmountWindow.xaml.cs"), f)


def test_null_resource_uses_path_stem():
    # resource null (the common case) -> match purely on the file stem
    static = [{"tool": "own-check", "rule": "OWN014", "category_name": "subscription-leak",
               "resource": None, "path": "UI/SettingsView.xaml.cs", "line": 5, "message": "leak"}]
    res = C.correlate(static, _dump(_retained("App.UI.SettingsView", 30)), CFG)
    _expect(len(res["confirmed"]) == 1 and res["confirmed"][0]["resource"] == "App.UI.SettingsView", res)


def test_runtime_only_confidence_respects_high_count():
    # excess 4: medium under high_count=10, high under a lowered high_count=3
    base = _dump(_retained("BlindVm", 5, expected=1))
    _expect(C.correlate([], base, CFG)["runtime_only"][0]["confidence"] == "medium", "medium")
    cfg_low = dict(CFG, high_count=3)
    _expect(C.correlate([], base, cfg_low)["runtime_only"][0]["confidence"] == "high", "high")


def test_non_leak_category_ignored():
    static = [_sf("StyleThing", cat="general-quality", rule="RCS1037")]
    res = C.correlate(static, _dump(_retained("StyleThing", 99)), CFG)
    _expect(not res["confirmed"] and not res["static_only"], res)   # not a leak category at all


def test_gate_blocks_confirmed_at_level():
    static = [_sf("LeakVm", event="Y.Changed")]
    res = C.correlate(static, _dump(_retained("LeakVm", 50, event_holder="X.Y")), CFG)
    _expect(not C.gate(res, "high")[0], "high confirmed blocks")
    # a medium-only confirmed passes a high gate but fails a medium gate
    res2 = C.correlate([_sf("MidVm", cat="idisposable-leak")], _dump(_retained("MidVm", 4)), CFG)
    _expect(C.gate(res2, "high")[0] and not C.gate(res2, "medium")[0], res2)


def test_shipped_config_loads():
    cfg = C.load_config()
    _expect("leak_categories" in cfg and cfg["high_count"] >= cfg["min_count"], cfg)


def test_confirmed_findings_have_canonical_shape():
    res = C.correlate([_sf("Vm", event="E.Changed")], _dump(_retained("Vm", 20, event_holder="H.E")), CFG)
    f = res["confirmed"][0]
    for k in ("tool", "rule", "category_name", "resource", "path", "line", "message", "suppressed"):
        _expect(k in f, f"missing {k}")
    _expect(f["suppressed"] is False, f)


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def test_cli_writes_outputs_and_gates():
    d = tempfile.mkdtemp(prefix="rt-")
    try:
        fp = os.path.join(d, "findings.json")
        rp = os.path.join(d, "runtime.json")
        out = os.path.join(d, "out")
        _write(fp, {"findings": [_sf("DocumentsViewModel", event="DocumentStore.Changed")]})
        _write(rp, _dump(_retained("DocumentsViewModel", 132, bytes_=88080384,
                                   event_holder="Sts.Broker.Documents.DocumentStore")))
        # report-only -> exit 0
        _expect(cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out]) == 0, "report-only")
        j = json.load(open(os.path.join(out, "runtime-findings.json"), encoding="utf-8"))
        _expect(len(j["findings"]) == 1 and j["findings"][0]["confidence"] == "high", j)
        _expect(os.path.exists(os.path.join(out, "runtime-report.md")), "report written")
        # gate@high -> exit 2
        rc = cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out, "--gate-level", "high"])
        _expect(rc == 2, rc)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cli_missing_runtime_exits_2():
    raised = None
    try:
        cli.main(["--runtime", os.path.join(tempfile.gettempdir(), "ownaudit-no-runtime-xyz.json")])
    except SystemExit as e:
        raised = e.code
    _expect(raised == 2, raised)


# ---- execution-state contract (Own.NET#331) --------------------------------
# The collector keeps "did not look" apart from "looked, found nothing" in its
# exit codes AND in the record. Correlation must honour the second one: a
# missing `retained` on a run that never happened is NO KNOWLEDGE, and reading
# it as an empty list files every static finding under "static-only (suspect
# FP)" — a verdict about evidence that does not exist.

def _record(state, **execution):
    return {"schema": "own-runtime/1", "execution": dict(state=state, **execution)}


def _refused():
    return _record("not_evaluated",
                   reason={"code": "refused-attach",
                           "stage": "open-target",
                           "detail": "Could not attach to process 4213",
                           "policy_in_force": "kernel.yama.ptrace_scope=1"})


def test_not_evaluated_record_is_refused_not_read_as_clean():
    raised = None
    try:
        C.correlate([_sf("DocumentsViewModel")], _refused(), CFG)
    except C.UnusableRuntimeRecord as e:
        raised = str(e)
    _expect(raised is not None, "a not_evaluated record must not correlate")
    _expect("refused-attach" in raised, raised)
    _expect("ptrace_scope" in raised, "the policy in force must reach the operator")
    # Relayed as what it is — in force — not as a proven cause the collector
    # never established.
    _expect("policy in force" in raised, raised)
    # The specific trap: silently reading it as "nothing retained".
    _expect(C.evaluation_problem(_refused()) is not None, "must not be usable")


def test_error_state_is_refused_and_names_the_classification():
    raised = None
    try:
        C.correlate([], _record("error", error={"classification": "IOException"}), CFG)
    except C.UnusableRuntimeRecord as e:
        raised = str(e)
    _expect(raised is not None and "IOException" in raised, raised)


def test_evaluated_without_scope_is_malformed_not_lenient():
    # A verdict that does not say what it looked at cannot mean "nothing was
    # there" — it takes the schema-violation path, not a quieter reading.
    doc = _record("clean")
    doc["verdict"] = "ABSENT"
    doc["retained"] = []
    raised = None
    try:
        C.correlate([], doc, CFG)
    except C.UnusableRuntimeRecord as e:
        raised = str(e)
    _expect(raised is not None and "scope" in raised, raised)


def test_unknown_state_is_refused_rather_than_guessed():
    raised = None
    try:
        C.correlate([], _record("mostly-fine", scope={"verb": "roots"}), CFG)
    except C.UnusableRuntimeRecord as e:
        raised = str(e)
    _expect(raised is not None and "refusing to guess" in raised, raised)


def test_evaluated_record_correlates_normally():
    doc = _dump(_retained("DocumentsViewModel", 132, event_holder="Sts.Broker.DocumentStore"))
    doc["execution"] = {"state": "observed",
                        "scope": {"verb": "roots", "mode": "attach", "instances_on_heap": 132}}
    res = C.correlate([_sf("DocumentsViewModel", event="DocumentStore.Changed")], doc, CFG)
    _expect(len(res["confirmed"]) == 1, res)
    _expect(C.evaluation_problem(doc) is None, "an observed record with scope is usable")


def test_pre_contract_record_still_correlates():
    # Records written before the execution block exists carry `retained` only
    # after evaluating, so they are measurements; the ambiguity they had was in
    # the ABSENCE of the file, which correlation is never handed.
    legacy = _dump(_retained("DocumentsViewModel", 132))
    _expect("execution" not in legacy, "fixture must model a pre-contract record")
    _expect(C.evaluation_problem(legacy) is None, "legacy measurement must stay usable")


def test_shapeless_record_is_refused():
    _expect(C.evaluation_problem({"schema": "own-runtime/1"}) is not None,
            "neither a measurement nor a record of one")


def test_cli_refuses_a_run_that_never_looked():
    d = tempfile.mkdtemp(prefix="rt-ne-")
    try:
        fp, rp = os.path.join(d, "findings.json"), os.path.join(d, "runtime.json")
        out = os.path.join(d, "out")
        _write(fp, {"findings": [_sf("DocumentsViewModel", event="DocumentStore.Changed")]})
        _write(rp, _refused())
        raised = None
        try:
            cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out])
        except SystemExit as e:
            raised = e.code
        _expect(raised == 2, f"a not_evaluated record must exit 2, got {raised}")
        # And no report: a written report is a claim that a pass ran.
        for name in cli.OUTPUTS:
            _expect(not os.path.exists(os.path.join(out, name)),
                    f"{name} may not be written for a run that never looked")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_refusal_invalidates_a_previous_runs_outputs():
    """The one a fresh temp-dir cannot catch. A good run yesterday, a refusal
    today, the SAME out-dir: leaving yesterday's report in place is the same
    false evidence, just aged. Nothing in the file says which run produced it,
    so a reader takes it for the current one."""
    d = tempfile.mkdtemp(prefix="rt-stale-")
    try:
        fp, rp = os.path.join(d, "findings.json"), os.path.join(d, "runtime.json")
        out = os.path.join(d, "out")
        _write(fp, {"findings": [_sf("DocumentsViewModel", event="DocumentStore.Changed")]})

        # Yesterday: a real pass, real outputs.
        good = _dump(_retained("DocumentsViewModel", 132, bytes_=88080384,
                               event_holder="Sts.Broker.Documents.DocumentStore"))
        good["execution"] = {"state": "observed",
                             "scope": {"verb": "roots", "mode": "attach",
                                       "instances_on_heap": 132}}
        _write(rp, good)
        _expect(cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out]) == 0, "good run")
        for name in cli.OUTPUTS:
            _expect(os.path.exists(os.path.join(out, name)), f"{name} must exist after a good run")

        # Today: the collector never looked.
        _write(rp, _refused())
        raised = None
        try:
            cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out])
        except SystemExit as e:
            raised = e.code
        _expect(raised == 2, f"refusal must exit 2, got {raised}")
        for name in cli.OUTPUTS:
            _expect(not os.path.exists(os.path.join(out, name)),
                    f"{name} survived a refusal — it now reads as this run's result")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_missing_dump_also_invalidates_previous_outputs():
    """Not only the refusal path. Every exit without a result has to leave the
    directory saying nothing rather than saying the last thing it knew."""
    d = tempfile.mkdtemp(prefix="rt-stale2-")
    try:
        fp, rp = os.path.join(d, "findings.json"), os.path.join(d, "runtime.json")
        out = os.path.join(d, "out")
        _write(fp, {"findings": [_sf("DocumentsViewModel", event="DocumentStore.Changed")]})
        _write(rp, _dump(_retained("DocumentsViewModel", 132,
                                   event_holder="Sts.Broker.Documents.DocumentStore")))
        _expect(cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out]) == 0, "good run")
        os.remove(rp)
        raised = None
        try:
            cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out])
        except SystemExit as e:
            raised = e.code
        _expect(raised == 2, f"a missing dump must exit 2, got {raised}")
        for name in cli.OUTPUTS:
            _expect(not os.path.exists(os.path.join(out, name)),
                    f"{name} survived a run with no dump to read")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_publish_leaves_no_temp_files_behind():
    d = tempfile.mkdtemp(prefix="rt-pub-")
    try:
        fp, rp = os.path.join(d, "findings.json"), os.path.join(d, "runtime.json")
        out = os.path.join(d, "out")
        _write(fp, {"findings": [_sf("DocumentsViewModel", event="DocumentStore.Changed")]})
        _write(rp, _dump(_retained("DocumentsViewModel", 132,
                                   event_holder="Sts.Broker.Documents.DocumentStore")))
        _expect(cli.main(["--findings", fp, "--runtime", rp, "--out-dir", out]) == 0, "good run")
        leftovers = sorted(n for n in os.listdir(out) if n not in cli.OUTPUTS)
        _expect(not leftovers, f"atomic publish left files behind: {leftovers}")
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
