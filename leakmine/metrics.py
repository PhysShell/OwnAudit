"""Metrics — aggregate verdicts into the numbers the study (and the README) can cite.

Every number here is honest about what it can and cannot claim (docs/leakfix-mine.md §6):
  - recall_on_corpus  — caught / real-fixes *in this mined corpus*. NOT recall on "all
                        leaks" — the corpus is selection-biased toward noticed+fixed bugs,
                        so this is a regression-suite score, not a population estimate.
  - unique_findings   — real fixes OwnAudit caught that no baseline did. The headline.
  - fp_after_rate     — per tool, share of candidates where it still fires post-fix on the
                        fixed file. A precision smell, not a precision number.
  - by_tier           — recall split by analysis resolution (syntactic/semantic/interproc):
                        how much is catchable with zero build vs needs references.
  - by_category       — the taxonomy distribution, same buckets as report/sarif.py.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .confirm import Verdict


@dataclass
class Report:
    n_candidates: int
    n_real_fixes: int
    recall_on_corpus: dict[str, float] = field(default_factory=dict)   # tool -> rate
    catches: dict[str, int] = field(default_factory=dict)             # tool -> count
    unique_to_ownaudit: int = 0
    fp_after_rate: dict[str, float] = field(default_factory=dict)
    by_tier: dict[str, int] = field(default_factory=dict)             # resolution -> own catches
    by_category: dict[str, int] = field(default_factory=dict)
    by_ecosystem: dict[str, int] = field(default_factory=dict)
    unique_miss: int = 0   # real fixes NO tool caught — the "what are we all missing" bucket

    def as_dict(self) -> dict:
        return {
            "n_candidates": self.n_candidates,
            "n_real_fixes": self.n_real_fixes,
            "recall_on_corpus": self.recall_on_corpus,
            "catches": self.catches,
            "unique_to_ownaudit": self.unique_to_ownaudit,
            "fp_after_rate": self.fp_after_rate,
            "by_tier": self.by_tier,
            "by_category": self.by_category,
            "by_ecosystem": self.by_ecosystem,
            "unique_miss": self.unique_miss,
        }


def aggregate(
    verdicts: list[Verdict],
    *,
    ownaudit_tool: str = "ownaudit",
    baseline_tools: tuple[str, ...] = (),
) -> Report:
    n = len(verdicts)
    real = [v for v in verdicts if v.is_real_fix]
    n_real = len(real)
    all_tools = (ownaudit_tool, *baseline_tools)

    catches = {t: 0 for t in all_tools}
    fp_counts = {t: 0 for t in all_tools}
    for v in verdicts:
        for t in v.caught_by:
            catches[t] = catches.get(t, 0) + 1
        for t in v.fp_after:
            fp_counts[t] = fp_counts.get(t, 0) + 1

    recall = {
        t: (catches[t] / n_real if n_real else 0.0) for t in all_tools
    }
    fp_rate = {t: (fp_counts[t] / n if n else 0.0) for t in all_tools}

    by_tier = Counter(v.own_resolution for v in real if v.own_resolution)
    by_cat = Counter(v.category for v in real)
    by_eco = Counter(v.ecosystem for v in real)
    unique = sum(1 for v in real if v.unique_to_ownaudit)
    unique_miss = sum(1 for v in real if not v.caught_by)

    return Report(
        n_candidates=n,
        n_real_fixes=n_real,
        recall_on_corpus={k: round(x, 4) for k, x in recall.items()},
        catches=dict(catches),
        unique_to_ownaudit=unique,
        fp_after_rate={k: round(x, 4) for k, x in fp_rate.items()},
        by_tier=dict(by_tier),
        by_category=dict(by_cat),
        by_ecosystem=dict(by_eco),
        unique_miss=unique_miss,
    )


def render_markdown(rep: Report) -> str:
    """A compact report block, in the house table style (docs are Russian; numbers speak)."""
    lines = [
        "# LeakFixMine — corpus metrics",
        "",
        f"- candidates: **{rep.n_candidates}**, confirmed real fixes: **{rep.n_real_fixes}**",
        f"- unique to OwnAudit (caught, no baseline did): **{rep.unique_to_ownaudit}**",
        f"- real fixes NO tool caught (shared blind spot): **{rep.unique_miss}**",
        "",
        "## Recall on corpus (regression-suite score, not population recall)",
        "",
        "| tool | catches | recall |",
        "|---|---:|---:|",
    ]
    for tool, rate in rep.recall_on_corpus.items():
        lines.append(f"| {tool} | {rep.catches.get(tool, 0)} | {rate:.0%} |")
    lines += ["", "## OwnAudit catches by analysis tier (build-dependency axis)", "",
              "| tier | catches |", "|---|---:|"]
    for tier, c in sorted(rep.by_tier.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {tier} | {c} |")
    lines += ["", "## By category", "", "| category | real fixes |", "|---|---:|"]
    for cat, c in sorted(rep.by_category.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cat} | {c} |")
    return "\n".join(lines) + "\n"
