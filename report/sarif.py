"""SARIF 2.1.0 export of OwnAudit findings → GitHub code scanning (Own.NET Auditor §3, phase 1).

Pure transform over the recorded `sts_audit/findings.json` — no .NET, testable in CI.
Maps findings into SARIF: one run per tool (each its own driver + deduped rule set),
results carrying ruleId/level/location, stable line-independent partialFingerprints (so
GitHub correlates an alert across edits), tier+category in properties, and suppression
passthrough. Severity is GitHub-friendly: real leaks → error, correctness/arch → warning,
style → note, with `min_level` / `max_results_per_run` so you export by severity instead
of dumping 9000 alerts on a reviewer.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

# reuse the fix-arm tier map as the single source of truth for T1..T4.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fix"))
try:
    from fixarm.tiers import tier_of
except Exception:                       # keep the exporter usable standalone
    def tier_of(rule, tool=""):         # noqa: D401
        return ""

SARIF_VERSION = "2.1.0"
SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
FINGERPRINT_KEY = "ownAudit/v1"
# GitHub code scanning rejects a SARIF run with more than this many results, so the
# default export caps each run here to stay uploadable (see CLI --max-results).
GITHUB_MAX_RESULTS_PER_RUN = 25000

# tool id (in findings.json) -> (display name, info URL)
_DRIVERS = {
    "roslyn": ("Roslyn analyzers", "https://github.com/dotnet/roslyn-analyzers"),
    "codeql": ("CodeQL", "https://codeql.github.com/"),
    "own-check": ("own-check (OwnAudit)", "https://github.com/PhysShell/OwnAudit"),
    "infersharp": ("Infer#", "https://github.com/microsoft/infersharp"),
}

# category_name -> SARIF level. Leaks are real bugs; correctness/arch are warnings;
# bulk style is a note (so it doesn't drown the signal in GitHub).
_LEVEL_BY_CATEGORY = {
    "subscription-leak": "error", "idisposable-leak": "error", "region-escape": "error",
    # a runtime-confirmed leak is the highest-signal finding we produce; a runtime-only leak
    # (static blind spot) is a real bug too but not yet localized to a fix site.
    "runtime-confirmed-leak": "error", "runtime-only-leak": "warning",
    "inpc-correctness": "warning", "wpf-freezable": "warning", "architecture": "warning",
    "general-quality": "note", "uncategorized": "note",
}
_LEVEL_RANK = {"none": 0, "note": 1, "warning": 2, "error": 3}


def _level(category) -> str:
    return _LEVEL_BY_CATEGORY.get(category, "warning")


def _norm(msg) -> str:
    """Normalize a message for fingerprinting: lowercase, digits→#, collapse spaces. This
    keeps the fingerprint stable when only identifiers/counts in the message differ."""
    s = re.sub(r"\d+", "#", (msg or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _fingerprint(f) -> str:
    """Stable, line-INDEPENDENT id (rule + path + normalized message) so an alert is the
    same across commits even if the line moved."""
    basis = "\n".join([f.get("rule") or "", f.get("path") or "", _norm(f.get("message"))])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _region(line) -> dict:
    try:
        ln = int(line)
    except (TypeError, ValueError):
        ln = 0
    return {"startLine": ln if ln >= 1 else 1}     # SARIF requires startLine >= 1


def to_sarif(findings, min_level=None, max_results_per_run=None) -> dict:
    """Build a SARIF 2.1.0 log: one run per tool. `min_level` drops results below a
    severity ('note'|'warning'|'error'); `max_results_per_run` caps each run (highest
    severity kept first) and records how many were dropped in run.properties."""
    if min_level is not None and min_level not in _LEVEL_RANK:
        raise ValueError(f"invalid min_level {min_level!r}; expected one of {sorted(_LEVEL_RANK)}")
    if max_results_per_run is not None and max_results_per_run < 0:
        raise ValueError("max_results_per_run must be >= 0")
    floor = _LEVEL_RANK.get(min_level, -1)
    by_tool: dict[str, list] = {}
    for f in findings:
        by_tool.setdefault(f.get("tool") or "unknown", []).append(f)

    runs = []
    for tool, fs in by_tool.items():
        name, uri = _DRIVERS.get(tool, (tool, ""))
        rule_index: dict[str, int] = {}
        fp_seen: dict[str, int] = {}
        rules, results = [], []
        for f in fs:
            lvl = _level(f.get("category_name"))
            if _LEVEL_RANK[lvl] < floor:
                continue
            rid = f.get("rule") or "UNKNOWN"
            if rid not in rule_index:
                rule_index[rid] = len(rules)
                cat = f.get("category_name")
                rules.append({
                    "id": rid, "name": rid,
                    "shortDescription": {"text": cat or rid},
                    "defaultConfiguration": {"level": _level(cat)},
                    "properties": {"tags": [t for t in (cat, tier_of(rid, tool)) if t]},
                })
            # stable base (line-independent), disambiguated per occurrence: identical
            # rule+path+message hits in one file would otherwise collide, and SARIF
            # consumers use partialFingerprints as result identity.
            base = _fingerprint(f)
            k = fp_seen.get(base, 0)
            fp_seen[base] = k + 1
            fp = base if k == 0 else f"{base}/{k}"
            res = {
                "ruleId": rid, "ruleIndex": rule_index[rid], "level": lvl,
                "message": {"text": f.get("message") or f"{rid}: {f.get('category_name') or ''}".strip()},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": f.get("path") or ""},
                    "region": _region(f.get("line"))}}],
                "partialFingerprints": {FINGERPRINT_KEY: fp},
                "properties": {"tier": tier_of(rid, tool), "category": f.get("category_name"),
                               "tool": tool, "resource": f.get("resource") or ""},
            }
            if f.get("suppressed"):
                res["suppressions"] = [{"kind": "inSource",
                                        "justification": f.get("suppress_reason") or ""}]
            results.append(res)

        run_props = {"resultCount": len(results)}
        if max_results_per_run is not None and len(results) > max_results_per_run:
            results.sort(key=lambda r: _LEVEL_RANK[r["level"]], reverse=True)
            run_props["dropped"] = len(results) - max_results_per_run
            results = results[:max_results_per_run]
        driver = {"name": name, "rules": rules}
        if uri:
            driver["informationUri"] = uri
        runs.append({"tool": {"driver": driver}, "columnKind": "utf16CodeUnits",
                     "results": results, "properties": run_props})

    return {"$schema": SCHEMA, "version": SARIF_VERSION, "runs": runs}
