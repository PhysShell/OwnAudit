"""Emit GitHub-ready audit artifacts from sts_audit/findings.json (Own.NET Auditor phase 1):

    python3 -m report.cli                       # -> report/out/{ownnet-audit.sarif,metrics.json,report.md}
    python3 -m report.cli --min-level warning   # GitHub-friendly: drop bulk style notes
    python3 -m report.cli --max-results 5000    # respect GitHub's per-run result cap

SARIF goes to code scanning; metrics.json / report.md are the human + CI summary.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

from .sarif import to_sarif, tier_of, _level, _LEVEL_RANK

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _metrics(findings) -> dict:
    tool = collections.Counter(f.get("tool") for f in findings)
    cat = collections.Counter(f.get("category_name") for f in findings)
    rule = collections.Counter(f.get("rule") for f in findings)
    level = collections.Counter(_level(f.get("category_name")) for f in findings)
    tier = collections.Counter(tier_of(f.get("rule"), f.get("tool") or "") for f in findings)
    return {
        "total": len(findings),
        "by_tool": tool.most_common(),
        "by_category": cat.most_common(),
        "by_level": level.most_common(),
        "by_tier": [(t, tier[t]) for t in ("T1", "T2", "T3", "T4")],
        "top_rules": rule.most_common(15),
    }


def _report_md(m: dict) -> str:
    def rows(pairs):
        return "\n".join(f"| {k} | {v:,} |" for k, v in pairs)
    return (
        f"# Own.NET Audit summary\n\n"
        f"**{m['total']:,} findings**\n\n"
        f"## By severity (SARIF level)\n\n| level | count |\n|---|---|\n{rows(m['by_level'])}\n\n"
        f"## By tier\n\n| tier | count |\n|---|---|\n{rows(m['by_tier'])}\n\n"
        f"## By tool\n\n| tool | count |\n|---|---|\n{rows(m['by_tool'])}\n\n"
        f"## By category\n\n| category | count |\n|---|---|\n{rows(m['by_category'])}\n\n"
        f"## Top rules\n\n| rule | count |\n|---|---|\n{rows(m['top_rules'])}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="report", description="Own.NET Auditor — SARIF/metrics export")
    ap.add_argument("--findings", default=os.path.join(ROOT, "sts_audit", "findings.json"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "report", "out"))
    ap.add_argument("--min-level", choices=("note", "warning", "error"), default=None,
                    help="drop results below this SARIF level (GitHub-friendly export)")
    ap.add_argument("--max-results", type=int, default=None,
                    help="cap results per run (highest severity kept first)")
    args = ap.parse_args(argv)

    with open(args.findings, encoding="utf-8") as fh:
        findings = json.load(fh)["findings"]

    sarif = to_sarif(findings, min_level=args.min_level, max_results_per_run=args.max_results)
    metrics = _metrics(findings)
    os.makedirs(args.out_dir, exist_ok=True)
    paths = {
        "ownnet-audit.sarif": json.dumps(sarif, indent=1),
        "metrics.json": json.dumps(metrics, indent=2),
        "report.md": _report_md(metrics),
    }
    for name, body in paths.items():
        with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    emitted = sum(len(r["results"]) for r in sarif["runs"])
    print(f"wrote {args.out_dir}/  ({len(findings):,} findings -> {emitted:,} SARIF results "
          f"across {len(sarif['runs'])} run(s); min_level={args.min_level})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
