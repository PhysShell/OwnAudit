"""Architecture-pass CLI (Own.NET Auditor docs/own-net-auditor.md §3, phase 3):

    # on the Windows stand, the Roslyn extractor writes sts_audit/graph.json, then:
    python3 -m arch.cli --graph sts_audit/graph.json --rules arch/rules.json

Writes arch/out/arch-findings.json (findings.json shape, ready for SARIF/diff/dashboard)
and arch/out/arch-report.md. Exits 0 always — this is detect-only; gating is the diff CLI's
job (feed these findings through report.diff_cli). Build-free, no .NET.
"""
from __future__ import annotations

import argparse
import collections
import json
import os

from .graph import Graph
from .rules import load_rules, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _report_md(findings: list, graph: Graph) -> str:
    by_rule = collections.Counter(f["rule"] for f in findings)
    rows = "\n".join(f"| `{r}` | {c:,} |" for r, c in by_rule.most_common()) or "| (none) | 0 |"
    sample = "\n".join(
        f"| `{f['rule']}` | {f.get('resource', '')} | {f.get('path', '')}:{f.get('line', '')} |"
        for f in findings[:50])
    sample_block = (f"\n## Findings (first 50)\n\n| rule | type | location |\n|---|---|---|\n{sample}\n"
                    if findings else "\n_No architecture findings._\n")
    return (
        f"# Own.NET Audit — architecture pass\n\n"
        f"Graph: **{len(graph.type_ids()):,}** internal types, "
        f"**{len(graph.edges):,}** dependency edges.\n\n"
        f"## By rule\n\n| rule | count |\n|---|---|\n{rows}\n"
        f"{sample_block}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="arch.cli",
                                 description="Own.NET Auditor — architecture pass over the symbol graph")
    ap.add_argument("--graph", default=os.path.join(ROOT, "sts_audit", "graph.json"),
                    help="symbol dependency graph emitted by the Roslyn extractor (docs/arch-graph.md)")
    ap.add_argument("--rules", default=None, help="rules file (default: arch/rules.json)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "arch", "out"))
    args = ap.parse_args(argv)

    if not os.path.exists(args.graph):
        print(f"error: no graph at {args.graph!r}; run the Roslyn extractor on the stand "
              f"first (see docs/arch-graph.md).")
        raise SystemExit(2)

    graph = Graph.load(args.graph)
    findings = run(graph, load_rules(args.rules))

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "arch-findings.json"), "w", encoding="utf-8") as fh:
        json.dump({"findings": findings}, fh, indent=2)
    with open(os.path.join(args.out_dir, "arch-report.md"), "w", encoding="utf-8") as fh:
        fh.write(_report_md(findings, graph))

    by_rule = collections.Counter(f["rule"] for f in findings)
    summary = ", ".join(f"{r}={c}" for r, c in by_rule.most_common()) or "clean"
    print(f"architecture pass: {len(findings):,} findings ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
