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


def _sf(resource, cat="subscription-leak", rule="OWN001"):
    return {"tool": "own-check", "rule": rule, "category_name": cat, "resource": resource,
            "path": f"Broker/{resource}.cs", "line": 10, "message": "no matching unsubscribe"}


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
    static = [_sf("DocumentsViewModel")]
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
    static = [_sf("PopupVm")]
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


def test_non_leak_category_ignored():
    static = [_sf("StyleThing", cat="general-quality", rule="RCS1037")]
    res = C.correlate(static, _dump(_retained("StyleThing", 99)), CFG)
    _expect(not res["confirmed"] and not res["static_only"], res)   # not a leak category at all


def test_gate_blocks_confirmed_at_level():
    static = [_sf("LeakVm")]
    res = C.correlate(static, _dump(_retained("LeakVm", 50, event_holder="X.Y")), CFG)
    _expect(not C.gate(res, "high")[0], "high confirmed blocks")
    # a medium-only confirmed passes a high gate but fails a medium gate
    res2 = C.correlate([_sf("MidVm", cat="idisposable-leak")], _dump(_retained("MidVm", 4)), CFG)
    _expect(C.gate(res2, "high")[0] and not C.gate(res2, "medium")[0], res2)


def test_shipped_config_loads():
    cfg = C.load_config()
    _expect("leak_categories" in cfg and cfg["high_count"] >= cfg["min_count"], cfg)


def test_confirmed_findings_have_canonical_shape():
    res = C.correlate([_sf("Vm")], _dump(_retained("Vm", 20, event_holder="H.E")), CFG)
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
        _write(fp, {"findings": [_sf("DocumentsViewModel")]})
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
