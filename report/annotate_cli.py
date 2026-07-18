"""Annotate a generated health-report.md with rule explanations.

The report generator prints finding lines as
    - `path:line` **[P1 · category]** (tool)
— category, but no rule id, and nothing that says what the rule *means*. This pass
joins each line back to findings.json by (path, line), appends the rule id + its
rules-map title (Russian included for OWN rules), and adds a legend appendix for every
referenced rule. A post-pass on purpose: it works no matter which generator produced
the report.

    python3 -m report.annotate_cli --report artifacts/health-report.md \
        --findings artifacts/findings.json [--out artifacts/health-report.annotated.md]
"""
from __future__ import annotations

import argparse
import collections
import json
import re

from report.rules_map import load_rules_map, describe

_LINE = re.compile(r"^(- `(?P<path>[^`:]+):(?P<line>\d+)` \*\*\[.*?\]\*\* \([^)]*\))\s*$")


def annotate(report_path: str, findings_path: str, out_path: str) -> None:
    with open(findings_path, encoding="utf-8") as fh:
        findings = json.load(fh)["findings"]
    by_site: dict = collections.defaultdict(list)
    for f in findings:
        rule = f.get("rule")
        if rule:
            by_site[(f.get("path", ""), int(f.get("line", 0) or 0))].append(rule)

    catalog = load_rules_map()
    seen_rules: dict = {}

    out_lines = []
    with open(report_path, encoding="utf-8") as fh:
        for raw in fh.read().splitlines():
            m = _LINE.match(raw)
            if not m:
                out_lines.append(raw)
                continue
            rules = by_site.get((m.group("path"), int(m.group("line"))), [])
            if not rules:
                out_lines.append(raw)
                continue
            notes = []
            for rule in dict.fromkeys(rules):  # de-dup, keep order
                d = describe(rule, catalog)
                seen_rules[rule] = d
                title = d.get("title") or rule
                ru = d.get("title_ru")
                notes.append("`%s` %s" % (rule, title + (" · %s" % ru if ru else "")))
            out_lines.append("%s — %s" % (m.group(1), "; ".join(notes)))

    if seen_rules:
        out_lines += ["", "## Rule legend — что означают правила", ""]
        for rule in sorted(seen_rules):
            d = seen_rules[rule]
            title = d.get("title") or rule
            link = " — [docs](%s)" % d["help"] if d.get("help") else ""
            ru = d.get("title_ru")
            why = d.get("why_ru")
            line = "- **`%s`** — %s%s" % (rule, title, link)
            if ru:
                line += "\n  - %s. %s" % (ru, why or "")
            out_lines.append(line)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out_lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Annotate health-report.md with rule explanations.")
    ap.add_argument("--report", required=True)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--out", default=None,
                    help="default: <report> with .md replaced by .annotated.md")
    args = ap.parse_args(argv)
    out = args.out or re.sub(r"\.md$", ".annotated.md", args.report)
    annotate(args.report, args.findings, out)
    print("annotated report written to %s" % out)


if __name__ == "__main__":
    main()
