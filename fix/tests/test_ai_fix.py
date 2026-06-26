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


# ---- verify -> revise loop: a weak first try, corrected on round 2 ---------

def test_ai_revise_loop_converges():
    d, _ = _tmp(SRC)
    bad = ("```csharp\n"
           "        public static int Run()\n"
           "        {\n"
           "            int x = Compute();\n"
           "            x = 0; // still here\n"
           "            return Compute();\n"
           "        }\n```")
    client = MockLlmClient([bad, GOOD_REPLY])

    def reaudit(wd):                       # content-aware: finding present iff 'x = 0;' remains
        body = open(os.path.join(wd, "Core", "Sample.cs"), encoding="utf-8").read()
        return [FINDING] if "x = 0;" in body else []

    try:
        applier = AiFixApplier([FINDING], client, reaudit=reaudit, before=[FINDING],
                               max_rounds=3, ctx=4)
        res = run_fix(before=[FINDING], workdir=d, rule=FINDING.rule, applier=applier,
                      reaudit=reaudit, tier_of=_review_tier)
        assert res.status == OK, res.ledger()
        assert len(client.calls) == 2      # round 1 rejected, round 2 accepted
        body = open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8").read()
        assert "x = 0;" not in body
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_revise_accumulates_history():
    # the stateless client only knows what we put in the prompt — so every prior rejected
    # attempt must be threaded forward, else the model can re-propose the same failing fix.
    d, _ = _tmp(SRC)
    bad1 = "```csharp\n            int x = Compute();\n            x = 0; // v1\n```"
    bad2 = "```csharp\n            int x = Compute();\n            x = 0; // v2\n```"
    client = MockLlmClient([bad1, bad2, GOOD_REPLY])

    def reaudit(wd):
        body = open(os.path.join(wd, "Core", "Sample.cs"), encoding="utf-8").read()
        return [FINDING] if "x = 0;" in body else []

    try:
        applier = AiFixApplier([FINDING], client, reaudit=reaudit, before=[FINDING],
                               max_rounds=3, ctx=4)
        res = run_fix(before=[FINDING], workdir=d, rule=FINDING.rule, applier=applier,
                      reaudit=reaudit, tier_of=_review_tier)
        assert res.status == OK, res.ledger()
        third = client.calls[2][1]                          # round-3 prompt
        assert "attempt 1" in third and "attempt 2" in third, third
        assert "// v1" in third and "// v2" in third, third
        assert f"the finding [{FINDING.rule}] is still reported" in third, third
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_loop_gives_up_after_max_rounds():
    d, _ = _tmp(SRC)
    bad = ("```csharp\n            int x = Compute();\n            x = 0; // nope\n```")
    client = MockLlmClient(bad)            # always leaves the finding

    def reaudit(wd):
        body = open(os.path.join(wd, "Core", "Sample.cs"), encoding="utf-8").read()
        return [FINDING] if "x = 0;" in body else []

    try:
        applier = AiFixApplier([FINDING], client, reaudit=reaudit, before=[FINDING],
                               max_rounds=2, ctx=4)
        applier.apply(d, FINDING.rule)
        assert len(client.calls) == 2 and [r for _, r in applier.skipped] == ["ai-gave-up"]
        # planning is side-effect-free; nothing accepted -> file unchanged
        assert open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8").read() == SRC
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_plans_findings_bottom_to_top():
    # two findings in one file: the lower-in-file one must be proposed FIRST so its
    # accepted edit can't shift the still-pending window of the one above it.
    src = "".join(f"line {i}\n" for i in range(1, 26))           # 25 lines
    d = tempfile.mkdtemp(prefix="aifix-")
    p = os.path.join(d, "Core", "Sample.cs")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    f_top = Finding("cs/x", "Core/Sample.cs", 5, tool="codeql", message="upper")
    f_bot = Finding("cs/x", "Core/Sample.cs", 20, tool="codeql", message="lower")
    try:
        # single-shot (reaudit=None): each finding gets exactly one _propose call,
        # so client.calls is the proposal order. ctx=1 keeps the windows apart.
        client = MockLlmClient("```csharp\nrewritten\n```")
        applier = AiFixApplier([f_top, f_bot], client, ctx=1)
        applier._plan(d)
        assert "line 20" in client.calls[0][1]      # bottom finding proposed first
        assert "line 5" in client.calls[1][1]       # top finding proposed second
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ai_plan_restores_tree_when_reaudit_raises():
    # if re-audit blows up mid-loop, the candidate written for it must not leak
    d, _ = _tmp(SRC)

    def boom(wd):
        raise RuntimeError("audit failed")

    try:
        applier = AiFixApplier([FINDING], MockLlmClient(GOOD_REPLY), reaudit=boom,
                               before=[FINDING], max_rounds=2, ctx=4)
        raised = False
        try:
            applier.dry_run(d, FINDING.rule)
        except RuntimeError:
            raised = True
        assert raised
        assert open(os.path.join(d, "Core", "Sample.cs"), encoding="utf-8").read() == SRC
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
