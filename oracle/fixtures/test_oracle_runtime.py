"""Runs the runtime correlation on the LeakyOracle golden fixtures. Bare python3 or pytest:

    PYTHONPATH=. python3 oracle/fixtures/test_oracle_runtime.py

Exercises phase 5 on real, oracle-shaped data: the static suspects (findings.json) the own-check
pass would emit for the oracle's two intentional leaks, correlated against the heap evidence
(runtime.json) that matches the headless leak proof. Asserts the three-way split:
  * both leaks CONFIRMED high (subscription + timer), each naming the leaked CLR type;
  * nothing static-only (both suspects retained);
  * the 250k transitively-retained QuoteRow surfaces as RUNTIME-ONLY (a static blind spot);
  * the high gate fails on the two confirmed leaks.

Pins the runtime.json contract the слой-2 ClrMD collector must emit for the oracle, and guards it
against drift (every retained type maps to a real oracle source file). -O-safe (explicit raises).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from runtime import correlate as C                                       # noqa: E402

FINDINGS = os.path.join(HERE, "findings.json")
RUNTIME = os.path.join(HERE, "runtime.json")
VM_DIR = os.path.join(ROOT, "oracle", "LeakyOracle", "ViewModels")

# Pinned config so this golden depends only on its own fixtures — unrelated tuning in the shared
# runtime/config.json must not silently shift the oracle's confirmed/runtime-only split or downgrade
# the expected `high` confidence. (Mirrors the default config; same convention as test_runtime.py.)
ORACLE_CFG = {
    "leak_categories": ["subscription-leak", "idisposable-leak", "region-escape"],
    "default_expected": 1, "min_count": 2, "high_count": 10,
}


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _correlate():
    findings = json.load(open(FINDINGS, encoding="utf-8"))["findings"]
    dump = json.load(open(RUNTIME, encoding="utf-8"))
    return C.correlate(findings, dump, ORACLE_CFG), dump


def test_both_oracle_leaks_are_confirmed_high():
    res, _ = _correlate()
    by_res = {f["resource"]: f for f in res["confirmed"]}
    _expect(set(by_res) == {"LeakyOracle.ViewModels.WatchlistViewModel",
                            "LeakyOracle.ViewModels.TickerViewModel"},
            f"expected both leaks confirmed, got {sorted(by_res)}")
    for t, f in by_res.items():
        _expect(f["confidence"] == "high", f"{t} should be high, got {f['confidence']}")
        _expect(f["retained"] == 50 and f["expected"] == 0, f)
    # the subscription leak confirms OWN001; the timer leak confirms OWN-TIMER
    _expect(by_res["LeakyOracle.ViewModels.WatchlistViewModel"]["static_rule"] == "OWN001", by_res)
    _expect(by_res["LeakyOracle.ViewModels.TickerViewModel"]["static_rule"] == "OWN-TIMER", by_res)


def test_nothing_is_static_only():
    res, _ = _correlate()
    _expect(res["static_only"] == [], f"both suspects should be retained, got "
                                      f"{[f['rule'] for f in res['static_only']]}")


def test_transitively_retained_rows_are_a_runtime_only_blind_spot():
    res, _ = _correlate()
    _expect(len(res["runtime_only"]) == 1, f"expected one blind-spot type, got {len(res['runtime_only'])}")
    ro = res["runtime_only"][0]
    _expect(ro["resource"] == "LeakyOracle.ViewModels.QuoteRow" and ro["retained"] == 250000, ro)
    _expect(ro["confidence"] == "high", ro)   # 250000 >> high_count


def test_high_gate_fails_on_the_two_confirmed_leaks():
    res, _ = _correlate()
    passed, blocking = C.gate(res, "high")
    _expect(not passed and len(blocking) == 2, f"high gate should block 2, got {len(blocking)}")


def test_confirmed_are_in_findings_json_shape():
    res, _ = _correlate()
    base = {"tool", "rule", "category_name", "resource", "path", "line", "message", "suppressed"}
    for f in res["confirmed"]:
        _expect(base <= set(f), f"confirmed finding missing base keys: {sorted(f)}")
        _expect(f["tool"] == "own-runtime" and f["category_name"] == "runtime-confirmed-leak", f)


def test_runtime_types_map_to_real_oracle_files():
    # guard the contract against drift: every retained type must be a real oracle view-model.
    _, dump = _correlate()
    for rec in dump["retained"]:
        short = rec["type"].rsplit(".", 1)[-1]
        _expect(os.path.isfile(os.path.join(VM_DIR, short + ".cs")),
                f"retained type {rec['type']} has no source {short}.cs under oracle ViewModels")


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
