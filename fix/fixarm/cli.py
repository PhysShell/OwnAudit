"""Fix-arm CLI. Two modes, same wrapper:

  # CI/Linux — drive a recorded fixture (no .NET):
  python3 -m fixarm.cli --fixture fix/fixtures/idisp001-clean --rule IDISP001

  # Windows stand — drive a real applier + re-audit (sketch; needs dotnet/roslynator):
  #   wire RoslynatorApplier(sln) + ScriptReaudit(Run-Audit.ps1, target, out)
  #   into run_fix() exactly as the fixture path does below.

Prints the coverage ledger and, for review-gated fixes, the reviewable patch.
Exit code: 0 ok/no-op/queued, 2 rejected (regression), 3 no-effect.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

from .appliers import ReplayApplier, ReplayReaudit
from .own_fix import OwnFixApplier
from .ai_fix import AiFixApplier, LocalLlmClient
from . import tiers
from .orchestrate import load_findings, run_fix, OK, REJECTED, NO_EFFECT, NO_OP, UNFIXABLE


def _seed_workdir(before_dir: str) -> str:
    d = tempfile.mkdtemp(prefix="fixarm-")
    for dp, _, names in os.walk(before_dir):
        for n in names:
            full = os.path.join(dp, n)
            dst = os.path.join(d, os.path.relpath(full, before_dir))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fixarm", description="Fix-arm safety wrapper")
    ap.add_argument("--fixture", required=True, help="fixture dir (before/ after/ *.findings.json)")
    ap.add_argument("--rule", required=True, help="diagnostic id to fix (e.g. IDISP001, OWN001)")
    ap.add_argument("--applier", choices=("replay", "own", "ai"), default=None,
                    help="replay = recorded after/ tree; own = the OWN001/OWN014 fixer; "
                         "ai = local-LLM proposer (always REVIEW). Default: own for OWN* rules, else replay.")
    ap.add_argument("--llm-url", default="http://localhost:11434/v1",
                    help="local OpenAI-compatible endpoint for --applier ai (default: Ollama)")
    ap.add_argument("--model", default="qwen2.5-coder", help="local model name for --applier ai")
    ap.add_argument("--max-rounds", type=int, default=3, help="--applier ai verify->revise rounds")
    ap.add_argument("--line-tol", type=int, default=0)
    ap.add_argument("--show-diff", action="store_true", help="print the reviewable patch")
    args = ap.parse_args(argv)

    # OWN* rules default to the OWN fixer; replay needs a recorded after/ tree, so
    # refuse it on a fixture that has none (else it reads the absent tree as deletions).
    kind = args.applier or ("own" if args.rule.startswith("OWN") else "replay")
    if kind == "replay" and not os.path.isdir(os.path.join(args.fixture, "after")):
        print(f"error: fixture {args.fixture!r} has no after/ tree; replay would read it as "
              f"file deletions. Use --applier own.", file=sys.stderr)
        return 2

    before = load_findings(os.path.join(args.fixture, "before.findings.json"))
    wd = _seed_workdir(os.path.join(args.fixture, "before"))
    try:
        sel = [f for f in before if f.rule == args.rule]
        # AI proposals are never auto-committed — force the REVIEW gate regardless of rule tier.
        gate_of = (lambda r, t="": tiers.T4) if kind == "ai" else tiers.tier_of
        if kind == "own":
            applier = OwnFixApplier(sel)
        elif kind == "ai":
            reaudit = ReplayReaudit(os.path.join(args.fixture, "after.findings.json"))
            applier = AiFixApplier(sel, LocalLlmClient(args.llm_url, args.model),
                                   reaudit=reaudit, before=before, max_rounds=args.max_rounds)
        else:
            applier = ReplayApplier(args.fixture)
        try:
            res = run_fix(
                before=before, workdir=wd, rule=args.rule, applier=applier,
                reaudit=ReplayReaudit(os.path.join(args.fixture, "after.findings.json")),
                line_tol=args.line_tol, tier_of=gate_of,
            )
        except FileNotFoundError:
            # re-audit was actually reached, but this fixture records no after.findings.json.
            # (no-op / unfixable rules return before re-audit, so they never hit this.)
            print(f"error: fixture {args.fixture!r} has no after.findings.json (needed to "
                  f"re-audit the applied fix).", file=sys.stderr)
            return 2

        print(json.dumps(res.ledger(), indent=2))
        if res.status == REJECTED:
            print(f"\nREJECTED — fix introduced {len(res.introduced)} new finding(s):", file=sys.stderr)
            for f in res.introduced:
                print(f"  + {f.rule} {f.path}:{f.line}  {f.message}", file=sys.stderr)
        elif res.status == OK and (args.show_diff or res.gate != "auto-commit"):
            print(f"\n--- reviewable patch (gate: {res.gate}) ---\n{res.diff}")

        return {OK: 0, NO_OP: 0, UNFIXABLE: 0, REJECTED: 2, NO_EFFECT: 3}.get(res.status, 0)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
