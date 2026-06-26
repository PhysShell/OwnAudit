"""Baseline diff + gate tests (docs/own-net-auditor.md phase 2). Bare python3 or pytest:

    PYTHONPATH=. python3 report/tests/test_baseline.py

Proves the diff is fingerprint-identity based: a line shift is not "new", duplicates diff
as a multiset, the gate fails only on new findings at/above its level, and a compact saved
baseline round-trips. -O-safe (explicit raises).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from report import baseline as bl                                          # noqa: E402
from report import diff_cli                                               # noqa: E402


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _f(rule, path, line, cat, message="m", tool="roslyn"):
    return {"rule": rule, "path": path, "line": line, "category_name": cat,
            "message": message, "tool": tool}


# a small accepted "legacy" baseline
BASE = [
    _f("INPC020", "Broker/A.cs", 10, "inpc-correctness", "raise for 'X'"),
    _f("RCS1037", "Broker/B.cs", 5, "general-quality", "trailing whitespace"),
    _f("OWN001", "Broker/C.xaml.cs", 72, "subscription-leak", "event subscribed", tool="own-check"),
]


def test_new_and_fixed_detected():
    cur = [
        BASE[0],                                                  # unchanged
        _f("CA2000", "Broker/D.cs", 8, "idisposable-leak", "dispose"),   # NEW (error)
    ]                                                              # BASE[1], BASE[2] -> fixed
    d = bl.diff(BASE, cur)
    _expect(len(d["new"]) == 1 and d["new"][0]["rule"] == "CA2000", d["new"])
    fixed_rules = sorted(f["rule"] for f in d["fixed"])
    _expect(fixed_rules == ["OWN001", "RCS1037"], fixed_rules)
    _expect(d["net"] == 1 - 2, d["net"])


def test_line_shift_is_not_new():
    # same finding, moved down the file -> identity is line-independent -> not new
    cur = [dict(BASE[0], line=999), BASE[1], BASE[2]]
    d = bl.diff(BASE, cur)
    _expect(d["new"] == [] and d["fixed"] == [], (d["new"], d["fixed"]))


def test_duplicates_diff_as_multiset():
    base = [BASE[0]]                                  # 1 copy
    cur = [BASE[0], dict(BASE[0], line=20), dict(BASE[0], line=30)]   # 3 copies (diff lines)
    d = bl.diff(base, cur)
    _expect(len(d["new"]) == 2 and not d["fixed"], (d["new"], d["fixed"]))


def test_gate_blocks_new_high_severity_only():
    cur = BASE + [_f("CA2213", "Broker/E.cs", 3, "idisposable-leak", "leak")]   # new error
    d = bl.diff(BASE, cur)
    passed, blk = bl.gate(d, "warning")
    _expect(not passed and len(blk) == 1, (passed, blk))
    # a new *note* (style) does not block at gate-level warning
    cur2 = BASE + [_f("RCS9", "Broker/F.cs", 1, "general-quality", "style")]
    p2, blk2 = bl.gate(bl.diff(BASE, cur2), "warning")
    _expect(p2 and not blk2, (p2, blk2))
    # ...but it does block when the gate is lowered to note
    p3, blk3 = bl.gate(bl.diff(BASE, cur2), "note")
    _expect(not p3 and len(blk3) == 1, (p3, blk3))


def test_identical_baseline_zero_delta():
    d = bl.diff(BASE, list(BASE))
    _expect(not d["new"] and not d["fixed"] and d["net"] == 0, d)


def test_compact_record_roundtrips():
    rec = bl.baseline_record(BASE)
    _expect(rec["count"] == 3 and len(rec["fingerprints"]) == 3, rec)
    d = bl.diff(rec, list(BASE))                      # compact record vs same findings
    _expect(not d["new"] and not d["fixed"], d)
    # and it still detects a new finding
    d2 = bl.diff(rec, BASE + [_f("CA2000", "Broker/Z.cs", 1, "idisposable-leak")])
    _expect(len(d2["new"]) == 1, d2["new"])


def _write(path, findings):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"findings": findings}, fh)


def test_cli_save_then_gate():
    d = tempfile.mkdtemp(prefix="diff-")
    try:
        base_fp = os.path.join(d, "findings.json")
        _write(base_fp, BASE)
        bpath = os.path.join(d, "baseline.json")
        out = os.path.join(d, "out")
        # save baseline, then gate the same findings -> PASS (exit 0)
        _expect(diff_cli.main(["--current", base_fp, "--baseline", bpath, "--save-baseline"]) == 0, "save")
        _expect(os.path.exists(bpath), "baseline written")
        _expect(diff_cli.main(["--current", base_fp, "--baseline", bpath, "--out-dir", out]) == 0, "clean gate")
        # introduce a new error-level finding -> FAIL (exit 2)
        cur_fp = os.path.join(d, "current.json")
        _write(cur_fp, BASE + [_f("CA2000", "Broker/New.cs", 9, "idisposable-leak")])
        rc = diff_cli.main(["--current", cur_fp, "--baseline", bpath, "--out-dir", out])
        _expect(rc == 2, rc)
        # ...but --report-only never fails the build
        rc2 = diff_cli.main(["--current", cur_fp, "--baseline", bpath, "--out-dir", out, "--report-only"])
        _expect(rc2 == 0, rc2)
        j = json.load(open(os.path.join(out, "diff.json"), encoding="utf-8"))
        _expect(j["new"] == 1 and j["passed"] is False, j)
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
