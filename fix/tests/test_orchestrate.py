"""Fix-arm safety-contract tests (docs/fix-arm.md §4/§9). Runnable on bare python3:

    python3 fix/tests/test_orchestrate.py

Also discoverable by pytest if present. Exercises the full wrapper on recorded
fixtures: select -> dry-run/diff -> apply -> re-audit -> assert-no-new -> tier gate.
No .NET needed — the applier and re-audit are replay adapters.
"""
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))      # repo root
sys.path.insert(0, os.path.join(ROOT, "fix"))

from fixarm import tiers                                            # noqa: E402
from fixarm.appliers import ReplayApplier, ReplayReaudit           # noqa: E402
from fixarm.orchestrate import (                                   # noqa: E402
    Finding, load_findings, run_fix, diff_findings,
    OK, REJECTED, UNFIXABLE, NO_OP,
)

FIX = os.path.join(ROOT, "fix", "fixtures")


def _workdir(fixture: str) -> str:
    """A fresh temp tree seeded with the fixture's before/ sources."""
    d = tempfile.mkdtemp(prefix="fixarm-")
    src = os.path.join(FIX, fixture, "before")
    for dirpath, _, names in os.walk(src):
        for n in names:
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, src)
            dst = os.path.join(d, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
    return d


@contextmanager
def _run(fixture: str, rule: str, line_tol: int = 0):
    """Run a fixture through the wrapper, yielding (result, workdir) so the test can
    inspect the patched/reverted tree, then always reap the temp workdir."""
    fdir = os.path.join(FIX, fixture)
    before = load_findings(os.path.join(fdir, "before.findings.json"))
    wd = _workdir(fixture)
    try:
        yield run_fix(
            before=before, workdir=wd, rule=rule,
            applier=ReplayApplier(fdir),
            reaudit=ReplayReaudit(os.path.join(fdir, "after.findings.json")),
            line_tol=line_tol,
        ), wd
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ---- tier map (docs/fix-arm.md §3) -----------------------------------------

def test_tier_map():
    assert tiers.tier_of("RCS1001") == tiers.T1            # promoted mechanical
    assert tiers.tier_of("RCS1146") == tiers.T2            # not promoted -> review
    assert tiers.tier_of("IDISP001") == tiers.T2
    assert tiers.tier_of("INPC020") == tiers.T2
    assert tiers.tier_of("OWN001") == tiers.T4
    assert tiers.tier_of("OWN014") == tiers.T4
    assert tiers.tier_of("cs/useless-assignment-to-local") == tiers.T3
    assert tiers.tier_of("NULLPTR_DEREFERENCE", tool="infersharp") == tiers.T3
    assert tiers.gate_for_tier(tiers.T1) == tiers.AUTO
    assert tiers.gate_for_tier(tiers.T2) == tiers.REVIEW
    assert tiers.gate_for_tier(tiers.T4) == tiers.REVIEW


# ---- diff primitive --------------------------------------------------------

def test_diff_findings_introduced_and_removed():
    before = [Finding("IDISP001", "Core/Mail.cs", 9)]
    after = [Finding("IDISP005", "Core/Mail.cs", 14)]
    removed, introduced = diff_findings(before, after)
    assert [f.rule for f in removed] == ["IDISP001"]
    assert [f.rule for f in introduced] == ["IDISP005"]


def test_line_tolerance_matches_within_distance():
    # Same finding shifted by 1 line: within tol -> matched (not removed+introduced);
    # the old bucketing flagged this as a false regression at bucket boundaries.
    before = [Finding("IDISP001", "Core/Mail.cs", 11)]
    after = [Finding("IDISP001", "Core/Mail.cs", 12)]
    assert diff_findings(before, after, line_tol=1) == ([], [])
    rm, ins = diff_findings(before, after, line_tol=0)   # exact -> not the same site
    assert [f.rule for f in rm] == ["IDISP001"] and [f.rule for f in ins] == ["IDISP001"]


# ---- happy path: clean T2 fix, gated to review -----------------------------

def test_clean_fix_ok_and_gated_to_review():
    with _run("idisp001-clean", "IDISP001") as (res, wd):
        assert res.status == OK, res.ledger()
        assert res.tier == tiers.T2
        assert res.gate == tiers.REVIEW            # T2 -> not auto-committed
        assert not res.committable                 # human review required
        assert len(res.targeted_removed) == 1
        assert res.introduced == []
        assert "using (var client" in res.diff and "+" in res.diff   # reviewable patch
        # the applier actually rewrote the tree to the fixed form
        with open(os.path.join(wd, "Core", "Mail.cs"), encoding="utf-8") as fh:
            assert "using (var client" in fh.read()


# ---- the crux: a fix that introduces a new finding is REJECTED + reverted ---

def test_regression_is_rejected_and_tree_reverted():
    with _run("idisp001-regress", "IDISP001") as (res, wd):
        assert res.status == REJECTED, res.ledger()
        assert [f.rule for f in res.introduced] == ["IDISP005"]
        assert not res.committable                 # never committed on regression
        assert res.reverted                        # safety contract: tree rolled back
        # the rejected patch must NOT remain in the tree
        with open(os.path.join(wd, "Core", "Mail.cs"), encoding="utf-8") as fh:
            body = fh.read()
        assert "using (client = new SmtpClient" not in body
        assert "// client.Dispose();" in body      # restored to the before/ state


# ---- detect-only is unfixable, not silently skipped ------------------------

def test_detect_only_is_unfixable():
    # CodeQL-only finding: route to UNFIXABLE without touching the tree.
    before = [Finding("cs/useless-assignment-to-local", "Core/Mail.cs", 9, tool="codeql")]
    called = {"applied": False}

    class SpyApplier:
        name = "spy"
        def dry_run(self, workdir, rule): return ""
        def apply(self, workdir, rule): called["applied"] = True

    res = run_fix(before, "/nonexistent", "cs/useless-assignment-to-local",
                  SpyApplier(), lambda wd: [])
    assert res.status == UNFIXABLE
    assert res.gate == tiers.UNFIXABLE
    assert called["applied"] is False          # applier never ran


# ---- nothing selected -> no-op ---------------------------------------------

def test_no_op_when_rule_absent():
    with _run("idisp001-clean", "RCS9999") as (res, _):
        assert res.status == NO_OP
        assert res.selected == 0


# ---- bare-python runner (no pytest needed) ---------------------------------

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
