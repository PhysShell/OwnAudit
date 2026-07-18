"""The rule-id → human-explanation catalog (hybrid, docs/collector-plan.md follow-up).

Third-party analyzer rules carry their official EN titles, harvested once from each
analyzer's own docs index into `report/rules/*.tsv` (readable, diffable, re-harvestable).
Own rules (`OWN*`, `XAML*`, `OWN-TIMER`) are hand-written in `report/rules_own.json`
with Russian explanations for the executive report. Everything else degrades to a
derived title (CodeQL slugs) or a documentation link (compiler CS, MSTEST) — and, at
worst, to the bare id, never a crash.

Consumers: viz/build_dashboard.py (legend/tooltips), report/annotate_cli.py
(health-report legend), report/exec_cli.py (executive report).
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# tsv file -> (tool label, helpUri pattern with {id})
_TSV_SOURCES = {
    "meziantou.tsv": ("Meziantou.Analyzer",
                      "https://github.com/meziantou/Meziantou.Analyzer/blob/main/docs/Rules/{id}.md"),
    "roslynator.tsv": ("Roslynator",
                       "https://josefpihrt.github.io/docs/roslynator/analyzers/{id}"),
    "wpfanalyzers.tsv": ("WpfAnalyzers",
                         "https://github.com/DotNetAnalyzers/WpfAnalyzers/blob/master/documentation/{id}.md"),
    "propertychanged.tsv": ("PropertyChangedAnalyzers",
                            "https://github.com/DotNetAnalyzers/PropertyChangedAnalyzers/blob/master/documentation/{id}.md"),
    "idisposable.tsv": ("IDisposableAnalyzers",
                        "https://github.com/DotNetAnalyzers/IDisposableAnalyzers/blob/master/documentation/{id}.md"),
    "extra.tsv": (None, None),  # per-row tool inferred below
}

_EXTRA_HELP = {
    "AsyncFixer": ("AsyncFixer", "https://github.com/semihokur/AsyncFixer"),
    "THREAD_SAFETY_VIOLATION": ("Infer#", "https://fbinfer.com/docs/all-issue-types"),
    "PULSE_RESOURCE_LEAK": ("Infer#", "https://fbinfer.com/docs/all-issue-types"),
    "NULLPTR_DEREFERENCE": ("Infer#", "https://fbinfer.com/docs/all-issue-types"),
}


def load_rules_map(root: str | None = None) -> dict:
    """id -> {title, help, tool, [title_ru, why_ru, fix_ru]}."""
    here = root or _HERE
    rules: dict = {}

    for fname, (tool, pattern) in _TSV_SOURCES.items():
        path = os.path.join(here, "rules", fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or "\t" not in line:
                    continue
                rid, title = line.split("\t", 1)
                row_tool, help_uri = tool, pattern.format(id=rid) if pattern else None
                if row_tool is None:  # extra.tsv: infer per id
                    for prefix, (t, h) in _EXTRA_HELP.items():
                        if rid.startswith(prefix):
                            row_tool, help_uri = t, h
                            break
                rules[rid] = {"title": title, "help": help_uri, "tool": row_tool}

    own_path = os.path.join(here, "rules_own.json")
    if os.path.exists(own_path):
        with open(own_path, encoding="utf-8") as fh:
            own = json.load(fh)
        for rid, entry in own.items():
            if rid.startswith("_"):
                continue
            entry = dict(entry)
            entry.setdefault("tool", "own-check")
            entry.setdefault("help", None)
            rules[rid] = entry

    return rules


def describe(rule_id: str, rules: dict) -> dict:
    """Resolve one rule id, degrading gracefully for families with no harvested table."""
    if rule_id in rules:
        return rules[rule_id]

    # CodeQL: the id IS a descriptive slug ("cs/useless-assignment-to-local").
    if rule_id.startswith("cs/"):
        slug = rule_id.replace("/", "-")
        title = rule_id.split("/", 1)[1].replace("-", " ").capitalize()
        return {"title": title, "tool": "CodeQL",
                "help": "https://codeql.github.com/codeql-query-help/csharp/%s/" % slug}

    # C# compiler diagnostics (CS0169, …).
    if rule_id.startswith("CS") and rule_id[2:].isdigit():
        return {"title": "C# compiler diagnostic %s" % rule_id, "tool": "csc",
                "help": "https://learn.microsoft.com/en-us/search/?terms=%s" % rule_id}

    # MSTest analyzers.
    if rule_id.startswith("MSTEST"):
        return {"title": "MSTest analyzer rule %s" % rule_id, "tool": "MSTest.Analyzers",
                "help": "https://learn.microsoft.com/en-us/dotnet/core/testing/mstest-analyzers/%s"
                        % rule_id.lower()}

    return {"title": rule_id, "help": None, "tool": None}
