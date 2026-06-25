"""AI-fixer tests (docs/fix-arm.md). Bare python3 or pytest:

    PYTHONPATH=fix python3 fix/tests/test_ai_fix.py

Drives the AiFixApplier through the SAME wrapper as every other applier, with a
MockLlmClient (no server). Proves the local-AI proposal is verified + gated, not
trusted: re-audit must accept it, the gate is REVIEW, a no-change/regression is
skipped or rolled back.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "fix"))

from fixarm import tiers                                              # noqa: E402
from fixarm.ai_fix import (                                          # noqa: E402
    AiFixApplier, MockLlmClient, build_user, parse_replacement,
)
from fixarm.orchestrate import Finding, run_fix, OK, REJECTED        # noqa: E402


def _tmp(src: str):
    d = tempfile.mkdtemp(prefix="aifix-")
    p = os.path.join(d, "Core", "Sample.cs")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    return d, p


# the residual a mechanical fixer can't touch: a CodeQL detect-only finding
SRC = ("namespace Sts.Core\n"
       "{\n"
       "    public static class Sample\n"
       "    {\n"
       "        public static int Run()\n"
       "        {\n"
       "            int x = Compute();\n"
       "            x = 0;            // cs/useless-assignment-to-local\n"
       "            return Compute();\n"
       "        }\n"
       "    }\n"
       "}\n")
FINDING = Finding("cs/useless-assignment-to-local", "Core/Sample.cs", 8,
                  tool="codeql", message="useless assignment to local 'x'")

# a model reply that rewrites the window (drops the useless assignment), fenced
GOOD_REPLY = (
    "Here is the fix:\n```csharp\n"
    "        public static int Run()\n"
    "        {\n"
    "            return Compute();\n"
    "        }\n"
    "```\n")


def _review_tier(rule, tool=""):
    return tiers.T4    # AI proposals are always REVIEW-gated, never auto


# ---- prompt + parser -------------------------------------------------------

def test_prompt_includes_finding_and_window():
    lines = SRC.splitlines(keepends=True)
    user = build_user("Core/Sample.cs", lines, 4, 10, FINDING)
    assert "cs/useless-assignment-to-local" in user and "useless assignment" in user
    assert "x = 0;" in user and "Replace lines 5..10" in user


def test_parse_replacement_extracts_fence():
    assert parse_replacement(GOOD_REPLY)[0].strip() == "public static int Run()"
    assert parse_replacement("no fence here") is None


# ---- full contract: proposal verified + REVIEW-gated -----------------------

def test_ai_fix_applied_verified_and_gated_to_review():
    d, _ = _tmp(SRC)
    try:
        applier = AiFixApplier([FINDING], MockLlmClient(GOOD_REPLY), ctx=4)
        res = run_fix(before=[FINDING], workdir=d, rule=FINDING.rule, applier=applier,
                      reaudit=lambda wd: [],                 # re-audit: finding gone, nothing new
                      tier_of=_review_tier)
        assert res.status == OK, res.ledger()
        assert res.gate == tiers.REVIEW and not res.committable   # never auto-commit
        with open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8") as fh:
            body = fh.read()
        assert "x = 0;" not in body and "return Compute();" in body
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_no_change_is_skipped_not_faked():
    d, _ = _tmp(SRC)
    try:
        applier = AiFixApplier([FINDING], MockLlmClient("I can't fix this."), ctx=4)
        original = open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8").read()
        applier.apply(d, FINDING.rule)
        assert open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8").read() == original
        assert [r for _, r in applier.skipped] == ["ai-no-change"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_regression_is_rejected_and_reverted():
    d, _ = _tmp(SRC)
    try:
        applier = AiFixApplier([FINDING], MockLlmClient(GOOD_REPLY), ctx=4)
        # re-audit pretends the AI patch introduced a new finding -> reject + revert
        regress = [Finding("CS0103", "Core/Sample.cs", 7, tool="roslyn", message="name does not exist")]
        res = run_fix(before=[FINDING], workdir=d, rule=FINDING.rule, applier=applier,
                      reaudit=lambda wd: regress, tier_of=_review_tier)
        assert res.status == REJECTED and res.reverted, res.ledger()
        with open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8") as fh:
            assert "x = 0;" in fh.read()                    # rolled back to original
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
