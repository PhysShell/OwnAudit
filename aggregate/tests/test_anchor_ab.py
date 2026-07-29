#!/usr/bin/env python3
"""`aggregate/anchor_ab.py` - the producer A/B harness for Own.NET#317.

The harness exists to decide an acceptance gate, so what has to be tested is not
that it runs: it is that it REFUSES. A differential that reports "clean" over a
candidate whose findings moved, vanished, or merged would be worse than no
differential at all, because it would carry a verdict.

So every check below is a defect the harness must catch, plus the two properties
that make the verdict mean anything: the one allowed transformation passes, and
the result does not depend on the order results appear in the file.

Run:  PYTHONPATH=. python3 aggregate/tests/test_anchor_ab.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from aggregate.anchor_ab import (  # noqa: E402
    build, column_coverage, differential, occurrence_coverage, read_anchored)

_FAILS: list[str] = []
_CHECKS = 0


def check(cond: bool, msg: str) -> None:
    global _CHECKS
    _CHECKS += 1
    if not cond:
        _FAILS.append(msg)


def _result(path: str, line: int, rule: str = "OWN001", resource: str = "disposable",
            column: int | None = None, level: str = "warning",
            message: str | None = None, suppressed: bool = False) -> dict:
    region: dict = {"startLine": line}
    if column is not None:
        region["startColumn"] = column
    res: dict = {
        "ruleId": rule,
        "level": level,
        # Deliberately NOT derived from the path: a fixture whose message moved
        # whenever the path moved would make every single-field case a two-field
        # case, and the relaxation pass would rightly refuse to pair it.
        "message": {"text": message or f"leak [resource: {resource}]"},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": path}, "region": region}}],
    }
    if suppressed:
        res["suppressions"] = [{"kind": "external"}]
    return res


def _sarif(results: list[dict]) -> dict:
    return {"version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "Own.NET"}}, "results": results}]}


def _write(doc: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".sarif")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def _diff(base: list[dict], cand: list[dict]) -> dict:
    bp, cp = _write(_sarif(base)), _write(_sarif(cand))
    try:
        return differential(read_anchored(bp), read_anchored(cp))
    finally:
        os.remove(bp)
        os.remove(cp)


def run() -> int:
    # ---- 1. THE ONE ALLOWED TRANSFORMATION -------------------------------
    base = [_result("a.cs", 10), _result("b.cs", 20, resource="subscription token")]
    cand = [_result("a.cs", 10, column=13),
            _result("b.cs", 20, resource="subscription token", column=9)]
    d = _diff(base, cand)
    check(d["clean"], f"null -> real column must be clean, got {d['must_be_zero']}")
    check(d["column_added"] == 2, f"both columns must count as added, got {d['column_added']}")

    # ---- 2. ORDER INDEPENDENCE -------------------------------------------
    # The property the whole design rests on: matching is a multiset, so reversing
    # the candidate's results changes nothing. Without it the harness would be
    # measuring the order of lines in a JSON file.
    d_rev = _diff(base, list(reversed(cand)))
    check(d_rev == d, "reversing the candidate's results must not change the report")

    # ---- 3. ADVISORY RULES ARE OUT OF SCOPE ------------------------------
    p = _write(_sarif([_result("a.cs", 1), _result("a.cs", 2, rule="OWN050")]))
    try:
        check(len(read_anchored(p)) == 1, "OWN050 advisories must be excluded from scope")
    finally:
        os.remove(p)

    # ---- 4. EVERY DEFECT CATEGORY IS CAUGHT ------------------------------
    # Each case is the allowed transformation PLUS one defect, so a category that
    # silently folded into `column_added` would still be visible here.
    _MSG = "x [resource: disposable]"
    cases = [
        ("added", [_result("a.cs", 10, column=13), _result("z.cs", 99, column=1)]),
        ("removed", []),
        ("line_changed", [_result("a.cs", 11, column=13)]),
        ("path_changed", [_result("other.cs", 10, column=13)]),
        ("rule_changed", [_result("a.cs", 10, rule="OWN014", column=13)]),
        ("severity_changed", [_result("a.cs", 10, level="error", column=13)]),
        ("suppression_changed", [_result("a.cs", 10, column=13, suppressed=True)]),
        ("column_still_missing_in_scope", [_result("a.cs", 10)]),
        ("invalid_column", [_result("a.cs", 10, column=0)]),
    ]
    one = [_result("a.cs", 10)]
    for cat, cand_results in cases:
        d = _diff(one, cand_results)
        check(d["must_be_zero"].get(cat, 0) >= 1,
              f"{cat}: must be reported, got {d['must_be_zero']}")
        check(not d["clean"], f"{cat}: a report carrying this defect must not be clean")

    # The resource discriminator is PARSED OUT OF the message, so the two cannot
    # vary independently in any SARIF a real producer could emit. A changed
    # resource is therefore labelled `message_changed`. That is the honest
    # outcome: the label is for diagnosis, and what the gate needs is that the
    # difference is counted somewhere and the report is not clean - never that it
    # is absorbed into `column_added`.
    d = _diff(one, [_result("a.cs", 10, resource="pool", column=13)])
    check(d["must_be_zero"]["message_changed"] == 1,
          f"a changed resource must surface (as message_changed), got {d['must_be_zero']}")
    check(not d["clean"], "a changed resource must not be clean")
    check(d["column_added"] == 0,
          "a changed resource must NOT be absorbed into the allowed transformation")

    # A reworded message with everything else identical.
    d = _diff([_result("a.cs", 10, message="old [resource: disposable]")],
              [_result("a.cs", 10, message="new [resource: disposable]", column=13)])
    check(d["must_be_zero"]["message_changed"] == 1,
          f"message_changed must be reported, got {d['must_be_zero']}")

    # ---- 5. DUPLICATE COLLAPSE ------------------------------------------
    # `column` joined the bridge's dedupe key in #318. That fix could equally have
    # COLLAPSED two records that were distinct - the category most likely to be
    # mistaken for success, because the report gets shorter.
    d = _diff([_result("a.cs", 10), _result("a.cs", 10)],
              [_result("a.cs", 10, column=13)])
    check(d["must_be_zero"]["unexpected_duplicate_collapse"] == 1,
          f"two identical records collapsing to one must be caught, got {d['must_be_zero']}")

    # ...and genuine multiplicity, preserved, is NOT a defect: two records sharing
    # a key and gaining two different columns is exactly what #318 is for.
    d = _diff([_result("a.cs", 10), _result("a.cs", 10)],
              [_result("a.cs", 10, column=13), _result("a.cs", 10, column=44)])
    check(d["clean"], f"preserved multiplicity must stay clean, got {d['must_be_zero']}")
    check(d["column_added"] == 2, f"both columns counted, got {d['column_added']}")

    # Order independence WITHIN a shared key - the case the earlier reversal check
    # cannot reach, because those two records had different keys. Two records that
    # are indistinguishable by definition must not be paired positionally: there is
    # no correspondence between them to preserve, so the columns are a multiset and
    # reversing them changes nothing. (A negative control confirmed the earlier
    # check alone did not catch a positional implementation.)
    d_rev = _diff([_result("a.cs", 10), _result("a.cs", 10)],
                  [_result("a.cs", 10, column=44), _result("a.cs", 10, column=13)])
    check(d_rev == d, "columns within one key must compare as a multiset, not by position")

    # ---- 6. A LOST OR ALTERED COLUMN IS NOT THE ALLOWED CHANGE -----------
    d = _diff([_result("a.cs", 10, column=13)], [_result("a.cs", 10)])
    check(d["must_be_zero"]["column_removed"] == 1,
          f"losing a column must be caught, got {d['must_be_zero']}")
    d = _diff([_result("a.cs", 10, column=13)], [_result("a.cs", 10, column=44)])
    check(d["must_be_zero"]["column_changed"] == 1,
          f"a moved column must be caught, got {d['must_be_zero']}")

    # ---- 7. A BOOL IS NOT A COLUMN --------------------------------------
    # `True` is an `int`; unguarded it would read as column 1 - the fabricated
    # coordinate the #317 contract exists to refuse.
    p = _write(_sarif([_result("a.cs", 10, column=True)]))  # type: ignore[arg-type]
    try:
        rec = read_anchored(p)[0]
        check(rec.column is None and rec.raw_column is True,
              f"a bool startColumn must not read as a column, got {rec.column!r}")
    finally:
        os.remove(p)

    # ---- 8. COVERAGE TABLE ----------------------------------------------
    p = _write(_sarif([
        _result("a.cs", 1, resource="subscription token", column=5),
        _result("b.cs", 2, resource="subscription token", column=7),
        _result("c.cs", 3, resource="disposable field"),
        _result("d.cs", 4, rule="OWN014", resource="subscription token", column=9),
    ]))
    try:
        cov = column_coverage(read_anchored(p))
    finally:
        os.remove(p)
    check(cov["with_column"] == 3 and cov["total"] == 4,
          f"coverage totals wrong: {cov['with_column']}/{cov['total']}")
    rows = {(r["rule"], r["resource"]): (r["with_column"], r["total"])
            for r in cov["rows"]}
    check(rows[("OWN001", "subscription token")] == (2, 2)
          and rows[("OWN001", "disposable field")] == (0, 1)
          and rows[("OWN014", "subscription token")] == (1, 1),
          f"per-(rule, resource) breakdown wrong: {rows}")

    # ---- 9. OCCURRENCE COVERAGE IS READ, NOT RECOMPUTED ------------------
    payload = {"findings": [
        {"tool": "own-check", "occurrence_id": "a" * 32},
        {"tool": "own-check", "occurrence_id": None},
        {"tool": "codeql", "occurrence_id": "b" * 32},
    ]}
    occ = occurrence_coverage(payload, "own-check")
    check(occ == {"producer": "own-check", "with_occurrence_id": 1, "total": 2},
          f"occurrence coverage must count only this producer, got {occ}")

    # ---- 10. THE VERDICT NEEDS BOTH HALVES -------------------------------
    # A candidate identical to the baseline has a perfectly clean differential and
    # is still a failed slice: nothing gained a column. The gate must say so.
    bp, cp = _write(_sarif(one)), _write(_sarif(one))
    try:
        rep = build(bp, cp, "0ded835", "bdb3307", "ddf99b9")
        # A candidate byte-identical to the baseline moved no finding, so every
        # drift category is zero - and it is still a FAILED slice, because
        # nothing gained a column. The gate must say so, and must say why.
        check(not rep["pass"], "a candidate identical to the baseline must NOT pass")
        z = rep["differential"]["must_be_zero"]
        check(z["column_still_missing_in_scope"] == 1,
              f"the reason must be named, got {z}")
        check(all(v == 0 for k, v in z.items()
                  if k != "column_still_missing_in_scope"),
              f"no OTHER category may fire on an identical candidate, got {z}")
        check(rep["inputs"]["baseline"]["digest"].startswith("sha256:"),
              "inputs must record a digest of the exact bytes read")
        check(rep["inputs"]["baseline"]["producer_commit"] == "0ded835",
              "the report must carry the producer commit verbatim")
    finally:
        os.remove(bp)
        os.remove(cp)

    bp = _write(_sarif([_result("a.cs", 10)]))
    cp = _write(_sarif([_result("a.cs", 10, column=13)]))
    try:
        rep = build(bp, cp, "0ded835", "bdb3307", "ddf99b9")
        check(rep["pass"], f"the allowed transformation must PASS, got {rep['differential']}")
    finally:
        os.remove(bp)
        os.remove(cp)

    for f in _FAILS:
        print(f"FAIL: {f}")
    print(f"anchor A/B harness: {len(_FAILS)} failed of {_CHECKS} checks")
    return 1 if _FAILS else 0


if __name__ == "__main__":
    raise SystemExit(run())
