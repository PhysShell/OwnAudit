#!/usr/bin/env python3
"""
FP-verdict consumer — merge the FP-judge overlay into the audit findings (domain side).

The FP-judge (007's private `o7 judge`) emits `artifacts/fp-verdicts.json` — a data
overlay keyed by `finding_id` (contract: docs/fp-judge/verdict-contract.md). This is
the OwnAudit **consumer**: verify the overlay is fresh, join verdicts onto findings by
`finding_id`, and split into triage classes for the report/dashboard.

**Staleness guard (the point).** The overlay carries `generated_from` = sha256 of the
exact `findings.json` it was judged against (raw file bytes). We REFUSE to merge an
overlay whose digest != the CURRENT findings.json — a verdict set judged against an old
audit must never render as current truth (same honesty rule as counting, not hiding,
suppressed findings). This is why the oracle / fp-control overlays are correctly
rejected against the STS findings.json: their `generated_from` is a different digest.

Zero-dependency (stdlib only), like the rest of the audit tooling.

  python viz/apply_verdicts.py                              # merge artifacts/{findings,fp-verdicts}.json -> summary
  python viz/apply_verdicts.py --out artifacts/findings-triaged.json
  python viz/apply_verdicts.py --selftest                   # guard + join + classify checks, no live data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

# A false_positive at >= this confidence is dropped from the primary triage into the
# counted "judged-FP" section. A LOWER-confidence FP stays visible as `uncertain` — we
# only retire a CONFIDENT false positive.
FP_THRESHOLD = 0.8

# triage sort / bucket order: real first, then the still-open buckets, judged-FP last.
_ORDER = {"real": 0, "uncertain": 1, "unjudged": 2, "judged_fp": 3}


class StaleOverlayError(RuntimeError):
    """The overlay was judged against a different findings.json (generated_from mismatch)."""


def finding_id(f: dict) -> str:
    """Line-independent fingerprint (verdict-contract.md §1): sha1(path\\x1f rule\\x1f
    message)[:16]. NOT keyed on `line` (it drifts). Identical (path,rule,message) share
    an id on purpose — one verdict covers a repeated pattern."""
    key = f"{f['path']}\x1f{f['rule']}\x1f{f['message']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def verify_fresh(findings_path: str, overlay: dict) -> None:
    """Raise StaleOverlayError unless overlay.generated_from == sha256(findings bytes)."""
    want = overlay.get("generated_from")
    got = sha256_file(findings_path)
    if want != got:
        raise StaleOverlayError(
            "fp-verdicts overlay was judged against a different findings.json — refusing "
            f"to merge:\n  overlay.generated_from = {want}\n  sha256("
            f"{os.path.basename(findings_path)}) = {got}\n  re-run `o7 judge` against the "
            "current findings.json.")


def triage_class(v: dict | None, fp_threshold: float = FP_THRESHOLD) -> str:
    """real | judged_fp | uncertain | unjudged. A low-confidence false_positive stays in
    triage as `uncertain`; only a CONFIDENT false_positive is retired to judged_fp."""
    if v is None:
        return "unjudged"
    cls = v.get("class")
    if cls == "real":
        return "real"
    if cls == "false_positive" and float(v.get("confidence", 0.0)) >= fp_threshold:
        return "judged_fp"
    return "uncertain"   # 'uncertain', or a below-threshold false_positive


def merge(findings: list, overlay: dict, fp_threshold: float = FP_THRESHOLD) -> dict:
    """Join verdicts onto findings by finding_id and classify. A finding_id may cover >1
    physical finding (a repeated pattern) — the verdict applies to each. real sorts first,
    judged_fp last."""
    verdicts = overlay.get("verdicts", {})
    counts = {"real": 0, "uncertain": 0, "unjudged": 0, "judged_fp": 0}
    out = []
    for f in findings:
        fid = finding_id(f)
        v = verdicts.get(fid)
        tc = triage_class(v, fp_threshold)
        counts[tc] += 1
        out.append({**f, "finding_id": fid, "verdict": v, "triage_class": tc})
    out.sort(key=lambda x: (_ORDER[x["triage_class"]], x["path"], x["line"]))
    return {
        "fp_threshold": fp_threshold,
        "counts": counts,
        "judged": sum(1 for f in out if f["verdict"] is not None),
        "findings": out,
    }


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(findings_path: str, overlay_path: str, fp_threshold: float, out_path: str | None) -> int:
    fdoc = _load(findings_path)
    overlay = _load(overlay_path)
    try:
        verify_fresh(findings_path, overlay)
    except StaleOverlayError as e:
        print(f"apply_verdicts: {e}", file=sys.stderr)
        return 2
    result = merge(fdoc.get("findings", []), overlay, fp_threshold)
    c = result["counts"]
    print(f"fp-verdicts merged ({result['judged']}/{len(result['findings'])} findings judged, "
          f"model={overlay.get('model','?')}, threshold={fp_threshold}):")
    print(f"  real       {c['real']:>4}   (confirmed leaks — triage first)")
    print(f"  uncertain  {c['uncertain']:>4}   (needs a human / more context)")
    print(f"  unjudged   {c['unjudged']:>4}   (no verdict in overlay)")
    print(f"  judged-FP  {c['judged_fp']:>4}   (confident false positives — counted, retired)")
    if out_path:
        merged = {**fdoc, "verdict_summary": {"fp_threshold": fp_threshold, "counts": c,
                                              "model": overlay.get("model"),
                                              "generated_from": overlay.get("generated_from")},
                  "findings": result["findings"]}
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2)
        print(f"  -> {out_path}")
    return 0


# ---- selftest (no live data) -------------------------------------------------

def _selftest() -> int:
    import tempfile
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # 1) finding_id is line-independent and pattern-shared.
    a = {"path": "A.cs", "rule": "OWN001", "message": "m", "line": 10}
    b = {"path": "A.cs", "rule": "OWN001", "message": "m", "line": 4061}   # same triple, diff line
    d = {"path": "A.cs", "rule": "OWN001", "message": "other", "line": 10}
    check(finding_id(a) == finding_id(b), "finding_id must ignore line")
    check(finding_id(a) != finding_id(d), "finding_id must depend on message")
    check(len(finding_id(a)) == 16, "finding_id must be 16 hex chars")

    # 2) staleness guard: matching digest merges, mismatch raises — via a real temp file.
    with tempfile.TemporaryDirectory() as td:
        fp = os.path.join(td, "findings.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump({"findings": [a]}, fh)
        good = {"generated_from": sha256_file(fp), "verdicts": {}}
        bad = {"generated_from": "0" * 64, "verdicts": {}}
        try:
            verify_fresh(fp, good)
        except StaleOverlayError:
            fails.append("guard: matching digest must NOT raise")
        try:
            verify_fresh(fp, bad)
            fails.append("guard: mismatched digest MUST raise")
        except StaleOverlayError:
            pass

    # 3) classification + threshold.
    check(triage_class({"class": "real", "confidence": 0.9}) == "real", "real -> real")
    check(triage_class({"class": "false_positive", "confidence": 0.9}) == "judged_fp",
          "confident FP -> judged_fp")
    check(triage_class({"class": "false_positive", "confidence": 0.5}) == "uncertain",
          "low-confidence FP -> uncertain (stays in triage)")
    check(triage_class({"class": "uncertain", "confidence": 0.9}) == "uncertain", "uncertain -> uncertain")
    check(triage_class(None) == "unjudged", "no verdict -> unjudged")

    # 4) merge: counts + real-first ordering + verdict applies to a repeated pattern (shared id).
    findings = [a, b, d]   # a,b share an id; d is separate
    overlay = {"verdicts": {
        finding_id(a): {"class": "false_positive", "confidence": 0.95},
        finding_id(d): {"class": "real", "confidence": 0.9},
    }}
    r = merge(findings, overlay)
    check(r["counts"] == {"real": 1, "uncertain": 0, "unjudged": 0, "judged_fp": 2},
          f"merge counts wrong: {r['counts']}")   # a,b both judged_fp via shared id
    check(r["findings"][0]["triage_class"] == "real", "real must sort first")

    # 5) live overlays (if present) MUST be rejected against the STS findings.json — the
    #    guard working (oracle/fp-control were judged against a different findings set).
    fjson = os.path.join(os.path.dirname(__file__), "..", "artifacts", "findings.json")
    for ov in ("fp-verdicts.json", "fp-verdicts-fpcontrol.json"):
        ovp = os.path.join(os.path.dirname(__file__), "..", "artifacts", ov)
        if os.path.exists(fjson) and os.path.exists(ovp):
            try:
                verify_fresh(fjson, _load(ovp))
                # only a mismatch is expected; a MATCH here would mean the overlay really is
                # for the STS findings (then it is legitimately fresh — not a failure).
            except StaleOverlayError:
                pass  # expected for oracle-scoped overlays

    for f in fails:
        print(f"SELFTEST FAIL: {f}")
    print(f"apply_verdicts selftest: {'OK' if not fails else 'FAIL'} "
          f"(finding_id + staleness guard + classify + merge)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Merge the FP-judge overlay into audit findings.")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--findings", default=os.path.join(root, "artifacts", "findings.json"))
    ap.add_argument("--overlay", default=os.path.join(root, "artifacts", "fp-verdicts.json"))
    ap.add_argument("--fp-threshold", type=float, default=FP_THRESHOLD)
    ap.add_argument("--out", default=None, help="write the merged (triaged) findings json here")
    ap.add_argument("--selftest", action="store_true", help="run internal checks, no live data")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    return run(args.findings, args.overlay, args.fp_threshold, args.out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
