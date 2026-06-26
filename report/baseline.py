"""Baseline diff + quality gate (Own.NET Auditor docs/own-net-auditor.md §3, phase 2).

Compares a saved baseline against the current findings and reports what is NEW vs
FIXED, so a CI gate can fail on *new* debt only — never the ~72k of accepted legacy.

Finding identity is the same stable, line-independent fingerprint the SARIF exporter
uses (rule + path + normalized message, per-occurrence disambiguated), so the gate and
GitHub's code-scanning alerts agree on what counts as "the same finding". That's why we
diff on fingerprints here rather than the fix-arm's distance-based `diff_findings`, which
is built for the small before/after of a single applied fix on one tree, not a
whole-corpus comparison between two audit runs.
"""
from __future__ import annotations

import collections

from .sarif import _fingerprint, _level, _LEVEL_RANK, tier_of


def occurrence_fingerprints(findings) -> dict:
    """Map fingerprint -> finding. Duplicate findings (same rule+path+normalized message)
    get `base/N` suffixes, so N copies in the baseline and M in current diff to exactly
    |M - N| new/fixed. Order-independent: the SET of fingerprints depends only on the
    multiset of findings, not their order."""
    seen, out = {}, {}
    for f in findings:
        base = _fingerprint(f)
        k = seen.get(base, 0)
        seen[base] = k + 1
        out[base if k == 0 else f"{base}/{k}"] = f
    return out


def baseline_record(findings) -> dict:
    """Compact, commit-friendly baseline: fingerprint + just enough to describe a fixed
    finding later (rule/path/category/tool — no long messages). What --save-baseline writes."""
    return {"count": len(findings),
            "fingerprints": [
                {"fp": fp, "rule": f.get("rule"), "path": f.get("path"),
                 "category_name": f.get("category_name"), "tool": f.get("tool")}
                for fp, f in occurrence_fingerprints(findings).items()]}


def _baseline_fps(baseline) -> dict:
    """Accept a baseline_record dict, a raw findings.json dict, or a findings list."""
    if isinstance(baseline, dict) and "fingerprints" in baseline:
        return {e["fp"]: e for e in baseline["fingerprints"]}
    findings = baseline["findings"] if isinstance(baseline, dict) else baseline
    return occurrence_fingerprints(findings)


def diff(baseline, current_findings) -> dict:
    """new = in current but not baseline; fixed = in baseline but not current."""
    base = _baseline_fps(baseline)
    cur = occurrence_fingerprints(current_findings)
    new = [cur[fp] for fp in cur if fp not in base]
    fixed = [base[fp] for fp in base if fp not in cur]
    return {"new": new, "fixed": fixed,
            "baseline_total": len(base), "current_total": len(cur),
            "net": len(new) - len(fixed)}


def gate(d: dict, gate_level: str = "warning") -> tuple:
    """(passed, blocking): blocking = the NEW findings at/above `gate_level`. A legacy
    ratchet typically blocks new error+warning and lets bulk style notes through."""
    floor = _LEVEL_RANK[gate_level]
    blocking = [f for f in d["new"] if _LEVEL_RANK[_level(f.get("category_name"))] >= floor]
    return (not blocking, blocking)


def summarize(findings) -> dict:
    """Counts by SARIF level and fix-tier for a list of findings (new or fixed)."""
    lvl = collections.Counter(_level(f.get("category_name")) for f in findings)
    tier = collections.Counter(tier_of(f.get("rule"), f.get("tool") or "") for f in findings)
    return {"by_level": lvl.most_common(), "by_tier": tier.most_common()}
