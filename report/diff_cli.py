"""Baseline diff + quality gate CLI (Own.NET Auditor phase 2):

    # establish a baseline from a known-good run (run once, on the stand):
    python3 -m report.diff_cli --save-baseline --baseline sts_audit/baseline.json

    # gate a new run against it (CI):
    python3 -m report.diff_cli --baseline sts_audit/baseline.json
    #   exit 0 if no NEW finding is at/above --gate-level, else exit 2

Writes diff.json + diff.md to --out-dir. The point: fail the build on *new* debt only,
never the accepted legacy backlog.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import baseline as bl
from .sarif import _level, tier_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_findings(path) -> list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["findings"]


def _diff_md(d: dict, passed: bool, blocking: list, gate_level: str) -> str:
    new_s, fixed_s = bl.summarize(d["new"]), bl.summarize(d["fixed"])

    def rows(pairs):
        return "\n".join(f"| {k} | {v:,} |" for k, v in pairs) or "| (none) | 0 |"
    verdict = ("✅ **PASS** — no new findings at/above "
               f"`{gate_level}`" if passed else
               f"❌ **FAIL** — {len(blocking):,} new finding(s) at/above `{gate_level}`")
    sample = "\n".join(
        f"| `{f.get('rule')}` | {_level(f.get('category_name'))} | {f.get('path')}:{f.get('line', '')} |"
        for f in blocking[:50])
    sample_block = (f"\n### New findings that block the gate (first 50)\n\n"
                    f"| rule | level | location |\n|---|---|---|\n{sample}\n" if blocking else "")
    return (
        f"# Own.NET Audit — baseline diff\n\n"
        f"{verdict}\n\n"
        f"| | count |\n|---|---|\n"
        f"| baseline | {d['baseline_total']:,} |\n| current | {d['current_total']:,} |\n"
        f"| **new** | **{len(d['new']):,}** |\n| **fixed** | **{len(d['fixed']):,}** |\n"
        f"| net debt delta | {d['net']:+,} |\n\n"
        f"### New by level\n\n| level | count |\n|---|---|\n{rows(new_s['by_level'])}\n\n"
        f"### New by tier\n\n| tier | count |\n|---|---|\n{rows(new_s['by_tier'])}\n\n"
        f"### Fixed by level\n\n| level | count |\n|---|---|\n{rows(fixed_s['by_level'])}\n"
        f"{sample_block}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="report.diff",
                                 description="Own.NET Auditor — baseline diff + quality gate")
    ap.add_argument("--baseline", default=os.path.join(ROOT, "sts_audit", "baseline.json"),
                    help="baseline file (compact record or a findings.json)")
    ap.add_argument("--current", default=os.path.join(ROOT, "sts_audit", "findings.json"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "report", "out"))
    ap.add_argument("--gate-level", choices=("note", "warning", "error"), default="warning",
                    help="fail on a NEW finding at/above this level (default: warning)")
    ap.add_argument("--report-only", action="store_true",
                    help="write the diff but always exit 0 (don't fail the build)")
    ap.add_argument("--save-baseline", action="store_true",
                    help="write current findings as the baseline (compact) and exit")
    args = ap.parse_args(argv)

    current = _load_findings(args.current)

    if args.save_baseline:
        rec = bl.baseline_record(current)
        os.makedirs(os.path.dirname(os.path.abspath(args.baseline)), exist_ok=True)
        with open(args.baseline, "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        print(f"wrote baseline {args.baseline}  ({rec['count']:,} findings -> "
              f"{len(rec['fingerprints']):,} fingerprints)")
        return 0

    if not os.path.exists(args.baseline):
        print(f"error: no baseline at {args.baseline!r}; create one with --save-baseline "
              f"from a known-good run.", file=sys.stderr)
        return 2
    with open(args.baseline, encoding="utf-8") as fh:
        baseline = json.load(fh)

    d = bl.diff(baseline, current)
    passed, blocking = bl.gate(d, args.gate_level)

    os.makedirs(args.out_dir, exist_ok=True)
    slim = {k: d[k] for k in ("baseline_total", "current_total", "net")}
    slim.update({"new": len(d["new"]), "fixed": len(d["fixed"]),
                 "gate_level": args.gate_level, "passed": passed, "blocking": len(blocking),
                 "new_findings": [{"rule": f.get("rule"), "path": f.get("path"),
                                   "line": f.get("line"), "level": _level(f.get("category_name")),
                                   "tier": tier_of(f.get("rule"), f.get("tool") or "")}
                                  for f in d["new"]]})
    with open(os.path.join(args.out_dir, "diff.json"), "w", encoding="utf-8") as fh:
        json.dump(slim, fh, indent=2)
    with open(os.path.join(args.out_dir, "diff.md"), "w", encoding="utf-8") as fh:
        fh.write(_diff_md(d, passed, blocking, args.gate_level))

    print(f"baseline {d['baseline_total']:,} -> current {d['current_total']:,}: "
          f"{len(d['new']):,} new, {len(d['fixed']):,} fixed (net {d['net']:+,}); "
          f"gate@{args.gate_level}: {'PASS' if passed else 'FAIL'} "
          f"({len(blocking):,} blocking)")
    if not passed and not args.report_only:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
