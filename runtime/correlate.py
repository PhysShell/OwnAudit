"""Runtime correlation — static leak finding × runtime evidence (Own.NET Auditor
docs/own-net-auditor.md §3, phase 5, killer feature #2).

This is the original "STS Runtime Analysis" idea, grounded. A static analyzer says "subscribes
to DocumentStore.Changed, no matching unsubscribe" — plausible, but is it actually leaking? The
runtime knows: after a scenario (open/close a window 10×) a heap dump shows how many instances
are still retained and who holds them. Correlating the two turns a *suspicion* into a
*confirmed leak with a confidence* — and, just as valuable, surfaces the two disagreements:
static findings the runtime never retained (likely false positives / unexercised paths) and
runtime retention the static pass never predicted (the analyzer's blind spots).

Same split as the rest of the project: the .NET heap-dump collector runs on the Windows stand
(dotnet-gcdump / ClrMD) and emits runtime.json (contract: docs/runtime-contract.md); this
correlation is pure stdlib over findings.json + runtime.json, so it runs and is tested in CI.
"""
from __future__ import annotations

import json
import os

TOOL = "own-runtime"
CONFIRMED = "runtime-confirmed-leak"
RUNTIME_ONLY = "runtime-only-leak"

# Static categories that describe a *retention* the runtime can confirm or refute.
DEFAULT_LEAK_CATEGORIES = ("subscription-leak", "idisposable-leak", "region-escape")

_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

_CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def load_config(path: str | None = None) -> dict:
    with open(path or _DEFAULT_CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


def _rooted_by_event(rec: dict) -> dict | None:
    """The first GC root that is a static event delegate (the classic WPF leak holder), or None."""
    for root in rec.get("roots", []):
        if root.get("kind") == "static-event":
            return root
    return None


def _confidence(excess: int, rec: dict, cfg: dict) -> str:
    """high = lots of retained instances, OR held by a static-event delegate and still growing
    (the smoking gun for an event leak). Otherwise the retention is real but modest → medium."""
    high_count = cfg.get("high_count", 10)
    min_count = cfg.get("min_count", 2)
    if excess >= high_count:
        return "high"
    if _rooted_by_event(rec) and excess >= min_count:
        return "high"
    return "medium"


def _bytes_note(rec: dict) -> str:
    mb = rec.get("bytes")
    return f"; ~{round(mb / 1048576)} MB retained" if mb else ""


def _held_note(rec: dict) -> str:
    root = _rooted_by_event(rec)
    return f" held by static {root.get('holder')}.{root.get('member')}" if root else ""


def _confirmed_finding(f: dict, rec: dict, count: int, expected: int, conf: str) -> dict:
    """A confirmed leak in findings.json shape (tool own-runtime), carrying the static rule it
    corroborates plus the runtime evidence and a confidence."""
    msg = (f"runtime-confirmed leak: {count} retained {f.get('resource')} instance(s) "
           f"(expected {expected}){_held_note(rec)}{_bytes_note(rec)} "
           f"[confirms static {f.get('rule')}]")
    return {"tool": TOOL, "rule": f.get("rule"), "category_name": CONFIRMED,
            "resource": f.get("resource"), "path": f.get("path", ""), "line": f.get("line", 0),
            "message": msg, "suppressed": False,
            "confidence": conf, "static_rule": f.get("rule"),
            "retained": count, "expected": expected}


def _runtime_only_finding(t: str, rec: dict, count: int, expected: int) -> dict:
    """Retention the static pass never flagged — a blind spot worth a new rule."""
    msg = (f"runtime leak NOT predicted by static analysis: {count} retained {t} instance(s) "
           f"(expected {expected}){_held_note(rec)}{_bytes_note(rec)} — static blind spot")
    return {"tool": TOOL, "rule": "RUNTIME-UNPREDICTED", "category_name": RUNTIME_ONLY,
            "resource": t, "path": "", "line": 0, "message": msg, "suppressed": False,
            "confidence": "high" if (count - expected) >= 10 else "medium",
            "retained": count, "expected": expected}


def correlate(static_findings, dump: dict, cfg: dict | None = None) -> dict:
    """Three-way split of leak findings against a heap dump:
      * confirmed   — static leak finding AND runtime retention agree (high-value, low-FP).
      * static_only — static leak finding, no runtime retention (likely FP or path not exercised).
      * runtime_only— runtime retention with no static finding (the analyzer's blind spot).
    """
    cfg = cfg or {}
    leak_cats = set(cfg.get("leak_categories", DEFAULT_LEAK_CATEGORIES))
    default_expected = cfg.get("default_expected", 1)
    min_count = cfg.get("min_count", 2)
    by_type = {r["type"]: r for r in dump.get("retained", []) if "type" in r}

    confirmed, static_only = [], []
    static_leak_types = set()
    for f in static_findings:
        if f.get("category_name") not in leak_cats:
            continue
        t = f.get("resource") or ""
        static_leak_types.add(t)
        rec = by_type.get(t)
        if rec is None:
            static_only.append(f)
            continue
        count = rec.get("count", 0)
        expected = rec.get("expected", default_expected)
        if count - expected < min_count:        # within noise — runtime does not confirm
            static_only.append(f)
            continue
        confirmed.append(_confirmed_finding(f, rec, count, expected,
                                            _confidence(count - expected, rec, cfg)))

    runtime_only = []
    high_count = cfg.get("high_count", 10)
    for t, rec in by_type.items():
        count = rec.get("count", 0)
        expected = rec.get("expected", default_expected)
        if (count - expected) >= high_count and t not in static_leak_types:
            runtime_only.append(_runtime_only_finding(t, rec, count, expected))

    return {"confirmed": confirmed, "static_only": static_only, "runtime_only": runtime_only}


def gate(result: dict, level: str = "high") -> tuple:
    """(passed, blocking): blocking = confirmed leaks at/above `level` confidence. CI can fail a
    PR on a runtime-confirmed leak — the highest-signal finding the auditor produces."""
    floor = _CONFIDENCE_RANK[level]
    blocking = [f for f in result["confirmed"]
                if _CONFIDENCE_RANK.get(f.get("confidence"), 0) >= floor]
    return (not blocking, blocking)
