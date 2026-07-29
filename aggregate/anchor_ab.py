#!/usr/bin/env python3
"""The producer A/B for a physical-anchor change (Own.NET#317, child of #266).

Own.NET#318 made own-check emit a real Roslyn `startColumn`. The question this
module answers is narrow and the whole point is that it stays narrow:

    did the producer change ONLY the physical anchor, and nothing else?

The honest answer is a differential, not a coverage number. A coverage table can
go up while findings quietly move, disappear, or merge; only a record-by-record
diff can say that the sole thing that changed is `startColumn: null -> a real
column`. So the deliverable is one report with three parts - a differential, a
start-column coverage table, and (from the normalizer, not from here) occurrence
coverage - and the acceptance criterion lives in the differential.

WHY A MULTISET, NOT A ZIP
-------------------------
Two SARIF files are not two aligned lists. Results may be emitted in a different
order, and identical findings legitimately repeat. Comparing by array position
would measure the order of lines in a JSON file; comparing by `occurrence_id`
would be worse, because the candidate is a DIFFERENT RUN and its run identity is
correctly different. So records are matched as a multiset on a key that says what
a finding IS, with multiplicity carried explicitly:

    producer, rule, path, start_line, message, level, suppressed, resource

`column` is deliberately NOT in that key - it is the thing under test. Matching on
it would make the harness agree with itself.

WHY MULTIPLICITY IS PART OF THE ANSWER
--------------------------------------
`column` entered the bridge's dedupe key in #318. That is the intended fix, but it
cuts both ways: a bug there could just as easily COLLAPSE two records that used to
be distinct. Counting each key rather than merely testing membership is what makes
that visible - `unexpected_duplicate_collapse` is a first-class category, not a
footnote.

THE ONE ALLOWED TRANSFORMATION
------------------------------
    baseline:  <finding>, no startColumn
    candidate: <finding>, startColumn = a real positive column

Everything else is a defect category with an expected count of zero: added,
removed, rule/path/line/message/severity/suppression changed, a column that is
still missing in scope, a non-positive column, a lost column, a changed column,
and a collapsed duplicate.

A changed-field category exists only because "one removed + one added" is a true
but useless description of a finding whose message was reworded. Leftovers are
paired by relaxing exactly one key field at a time, in a fixed order, over
canonically sorted lists - so the classification is deterministic and a real
single-field drift is named rather than reported as an unrelated add/remove pair.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not compute `occurrence_id`. That is `aggregate/normalize.py`'s job and it
needs a provenance manifest; duplicating the identity gate here would create a
second implementation of the thing being certified. `--normalized` accepts that
module's v2 payload and reports its coverage alongside, so one report carries both
metrics without either half re-deriving the other.

It also does not decide whether the two inputs are comparable. Provenance is an
input to this tool, not an output of it: the caller states which producer commit
each file came from, and the report records those strings verbatim. `--baseline-
commit 0ded835` proves only that someone could type `0ded835`; the binding of a
producer commit to the binary that emitted a SARIF has to be OBSERVED at capture
time, by the runner, and carried in its own manifest.

TWO MODES
---------
Diagnostic (default) answers "did anything but the anchor move?" for any pair.
`--acceptance-ownnet-317` additionally pins what makes the answer count for that
issue: the exact 380-row STS ledger on BOTH sides, a baseline that is genuinely
line-only, and full occurrence coverage from the normalized payload. Acceptance
mode without `--normalized` exits 2 rather than deciding, because a gate that
could not be evaluated must never be reported as one that passed.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from aggregate.sarif_read import norm_path  # noqa: E402

#: Rules that are advisory rather than scored. The STS corpus carries 233 OWN050
#: advisories among 613 results; the in-scope population for Own.NET#317 is the
#: remaining 380. Overridable, because "which rules are advisory" is a policy of
#: the producer and not a fact about SARIF.
DEFAULT_ADVISORY = ("OWN050",)

#: own-check writes the resource discriminator into the message tail as
#: `[resource: subscription token]`. It is not a SARIF field, so it is recovered
#: by an exact-shape match rather than a loose search: this is a discriminator in
#: the match key, and a fuzzy one would silently merge two populations.
_RESOURCE = re.compile(r"\[resource: ([^\]\n]+)\]")

#: The key fields, in the order the relaxation pass tries them. Order matters only
#: for how a multi-field drift is LABELLED, never for whether it is caught: any
#: record differing in two or more fields stays an add/remove pair.
KEY_FIELDS = ("rule", "path", "start_line", "message", "level",
              "suppressed", "resource")

#: Field -> the category name the acceptance contract states. `start_line` is
#: reported as `line_changed`, `level` as `severity_changed` and `suppressed` as
#: `suppression_changed`: the report is read against the contract, so it spells
#: the categories the way the contract does rather than the way this file's
#: attributes are named.
CATEGORY = {"start_line": "line", "level": "severity", "suppressed": "suppression"}


def _category(field: str) -> str:
    return f"{CATEGORY.get(field, field)}_changed"


#: Key fields that are DERIVED from another key field and therefore cannot vary
#: independently of it. `resource` is parsed out of `message`, so no SARIF a real
#: producer could emit changes one without the other. It stays in the match key -
#: it is part of what a finding IS, and it survives the producer ever moving the
#: marker into `properties` - but the relaxation pass must ignore it while
#: relaxing its source, or a reworded message would look like a two-field drift
#: and be reported as an unrelated add/remove pair.
DERIVED = {"message": ("resource",)}

#: The in-scope ledger Own.NET#317 states for the recorded STS corpus. Gated
#: EXACTLY, not as a lower bound: an A/B whose only corpus check is "more than
#: zero findings" would pass on a single-finding replay, and a matching breakdown
#: on both sides is also the cheapest available evidence that the two runs saw the
#: same source snapshot rather than two trees that merely resemble each other.
STS_317_LEDGER = {
    ("OWN001", "subscription token"): 326,
    ("OWN001", "disposable field"): 24,
    ("OWN001", "disposable"): 23,
    ("OWN014", "subscription token"): 7,
}
STS_317_TOTAL = 380


class AcceptanceInputError(RuntimeError):
    """Acceptance mode was asked for without the inputs it needs to decide."""


@dataclass(frozen=True)
class Anchored:
    """One scored SARIF result, split into its identity and the column under test."""

    rule: str
    path: str
    start_line: int
    message: str
    level: str
    suppressed: bool
    resource: str
    #: `region.startColumn` as the producer reported it. `None` means absent -
    #: never 0, never 1, and never recovered by re-reading the source line.
    column: int | None
    #: Present and unparsed when the producer emitted something that is not a
    #: 1-based integer. Kept rather than coerced so `invalid_column` can report
    #: what was actually seen.
    raw_column: Any = None

    def key(self) -> tuple[Any, ...]:
        return tuple(getattr(self, f) for f in KEY_FIELDS)


def _column_of(region: dict[str, Any]) -> tuple[int | None, Any]:
    """`(column, raw)` - a column only when it is genuinely a 1-based integer.

    `True` is an `int` in Python and would otherwise read as column 1, which is
    exactly the fabricated coordinate the #317 contract refuses; it is rejected
    explicitly rather than by accident.
    """
    raw = region.get("startColumn")
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return None, raw
    return raw, None


def read_anchored(path: str, strips: list[str] | None = None,
                  advisory: tuple[str, ...] = DEFAULT_ADVISORY) -> list[Anchored]:
    """Every SCORED result of a one-run own-check SARIF, as `Anchored` records.

    `utf-8-sig`, like every other reader here: the file may have been written by
    Windows PowerShell, and a BOM would surface as "not valid JSON" rather than as
    an encoding detail.
    """
    with open(path, encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    out: list[Anchored] = []
    for run in doc.get("runs", []):
        for res in run.get("results", []):
            rule = str(res.get("ruleId", ""))
            if rule in advisory:
                continue
            locs = res.get("locations") or [{}]
            phys = (locs[0] or {}).get("physicalLocation", {}) or {}
            region = phys.get("region", {}) or {}
            uri = ((phys.get("artifactLocation") or {}).get("uri") or "")
            col, raw = _column_of(region)
            msg = ((res.get("message") or {}).get("text") or "")
            m = _RESOURCE.search(msg)
            out.append(Anchored(
                rule=rule,
                path=norm_path(uri, strips or []),
                start_line=int(region.get("startLine") or 0),
                message=msg,
                level=str(res.get("level") or "warning"),
                # SARIF marks a suppressed result with a non-empty `suppressions`
                # array. Absent and empty both mean "not suppressed", and the two
                # must not be told apart here - a producer that starts emitting
                # `[]` has not changed any verdict.
                suppressed=bool(res.get("suppressions")),
                resource=m.group(1) if m else "",
                column=col, raw_column=raw))
    return out


def _bag(records: list[Anchored]) -> dict[tuple[Any, ...], list[Anchored]]:
    bag: dict[tuple[Any, ...], list[Anchored]] = collections.defaultdict(list)
    for r in records:
        bag[r.key()].append(r)
    return bag


def _sortable(rec: Anchored) -> tuple[Any, ...]:
    """A total order over records, for deterministic greedy pairing."""
    return (rec.path, rec.start_line, rec.rule, rec.resource, rec.level,
            rec.suppressed, rec.message)


def _pair_leftovers(base: list[Anchored], cand: list[Anchored],
                    counts: collections.Counter) -> None:
    """Name single-field drifts among records no exact key matched.

    Greedy over canonically sorted lists, one relaxed field at a time. A record
    differing in two or more key fields is never paired - it stays an add and a
    remove, which is the honest description of "this is a different finding".
    """
    remaining_b = sorted(base, key=_sortable)
    remaining_c = sorted(cand, key=_sortable)
    for field in KEY_FIELDS:
        ignore = {field, *DERIVED.get(field, ())}
        others = [f for f in KEY_FIELDS if f not in ignore]
        by_rest: dict[tuple[Any, ...], list[Anchored]] = collections.defaultdict(list)
        for c in remaining_c:
            by_rest[tuple(getattr(c, f) for f in others)].append(c)
        still_b: list[Anchored] = []
        for b in remaining_b:
            bucket = by_rest.get(tuple(getattr(b, f) for f in others))
            if bucket:
                bucket.pop(0)
                counts[_category(field)] += 1
            else:
                still_b.append(b)
        remaining_b = still_b
        remaining_c = sorted((c for bucket in by_rest.values() for c in bucket),
                             key=_sortable)
    counts["removed"] += len(remaining_b)
    counts["added"] += len(remaining_c)


def differential(base: list[Anchored], cand: list[Anchored]) -> dict[str, Any]:
    """The differential report: every category, and the one allowed transformation."""
    bb, cb = _bag(base), _bag(cand)
    counts: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)

    def note(cat: str, rec: Anchored, extra: str = "") -> None:
        if len(examples[cat]) < 5:
            examples[cat].append(
                f"{rec.path}:{rec.start_line} {rec.rule} [{rec.resource}]{extra}")

    leftover_b: list[Anchored] = []
    leftover_c: list[Anchored] = []
    for key in set(bb) | set(cb):
        b, c = bb.get(key, []), cb.get(key, [])
        # Multiplicity is compared before anything else: `column` joined the
        # bridge's dedupe key in #318, so a defect there would show up here as a
        # count that shrank, not as a record that changed.
        # Only when BOTH sides carry the key: a key on one side alone is an added
        # or removed finding, and charging it here would fire on every unmatched
        # record and drown the category it exists to expose.
        if b and c and len(b) != len(c):
            counts["unexpected_duplicate_collapse"] += abs(len(b) - len(c))
            note("unexpected_duplicate_collapse", b[0],
                 f" baseline x{len(b)} -> candidate x{len(c)}")
        paired = min(len(b), len(c))
        leftover_b.extend(b[paired:])
        leftover_c.extend(c[paired:])
        # Within a matched key, columns are compared as a multiset - the records
        # are indistinguishable by definition, so pairing them individually would
        # be inventing a correspondence.
        bcols = collections.Counter(r.column for r in b[:paired])
        ccols = collections.Counter(r.column for r in c[:paired])
        for rec in c[:paired]:
            if rec.raw_column is not None:
                counts["invalid_column"] += 1
                note("invalid_column", rec, f" startColumn={rec.raw_column!r}")
        gained = ccols[None] < bcols[None]
        counts["column_added"] += max(0, bcols[None] - ccols[None])
        lost = max(0, ccols[None] - bcols[None])
        if lost:
            counts["column_removed"] += lost
            note("column_removed", c[0])
        # A column that was already present and is now a DIFFERENT number is not
        # the allowed transformation and must not be absorbed by it.
        for col, n in ccols.items():
            if col is not None and bcols[col] < n and not gained:
                counts["column_changed"] += n - bcols[col]
                note("column_changed", c[0], f" -> {col}")
        if ccols[None]:
            counts["column_still_missing_in_scope"] += ccols[None]
            note("column_still_missing_in_scope", c[0])

    _pair_leftovers(leftover_b, leftover_c, counts)
    for cat in ("removed", "added"):
        for rec in (leftover_b if cat == "removed" else leftover_c)[:5]:
            note(cat, rec)

    zeros = ["added", "removed", "column_still_missing_in_scope", "invalid_column",
             "column_removed", "column_changed", "unexpected_duplicate_collapse",
             *(_category(f) for f in KEY_FIELDS)]
    return {
        "baseline_scored": len(base),
        "candidate_scored": len(cand),
        "column_added": counts["column_added"],
        "must_be_zero": {k: counts[k] for k in zeros},
        "clean": all(counts[k] == 0 for k in zeros),
        "examples": {k: v for k, v in sorted(examples.items()) if v},
    }


def column_coverage(records: list[Anchored]) -> dict[str, Any]:
    """`startColumn` coverage, broken down the way Own.NET#317 states the ledger."""
    per: dict[tuple[str, str], list[int]] = collections.defaultdict(lambda: [0, 0])
    for r in records:
        cell = per[(r.rule, r.resource)]
        cell[1] += 1
        if r.column is not None:
            cell[0] += 1
    rows = [{"rule": k[0], "resource": k[1], "with_column": v[0], "total": v[1]}
            for k, v in sorted(per.items())]
    return {"rows": rows,
            "with_column": sum(r["with_column"] for r in rows),
            "total": sum(r["total"] for r in rows)}


def occurrence_coverage(payload: dict[str, Any], producer: str) -> dict[str, Any]:
    """Occurrence coverage for one producer, read from a `normalized-findings/v2` payload.

    Read, not recomputed. `aggregate/normalize.py` owns the identity gate; a second
    implementation here would be certifying itself.
    """
    recs = [r for r in payload.get("findings", []) if r.get("tool") == producer]
    with_id = sum(1 for r in recs if r.get("occurrence_id"))
    return {"producer": producer, "with_occurrence_id": with_id, "total": len(recs)}


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return "sha256:" + hashlib.sha256(fh.read()).hexdigest()


def render(report: dict[str, Any]) -> str:
    """ASCII-only text report. The evidence a human reads is the same one CI gates."""
    out: list[str] = []
    inp = report["inputs"]
    out.append("Own.NET#317 producer A/B - physical anchor only")
    out.append("")
    out.append("inputs")
    for side in ("baseline", "candidate"):
        s = inp[side]
        out.append(f"  {side:9} producer={s['producer_commit']}")
        out.append(f"  {'':9} sarif={s['sarif']}")
        out.append(f"  {'':9} {s['digest']}")
    out.append(f"  normalizer   {inp['normalizer_commit']}")
    out.append("")
    bcov = report["baseline_column_coverage"]
    out.append("start-column coverage, BASELINE (scored)")
    out.append(f"  {bcov['with_column']}/{bcov['total']}   "
               "(must be 0/N: the transformation under test is null -> a column)")
    out.append("")
    cov = report["column_coverage"]
    out.append("start-column coverage, CANDIDATE (scored)")
    out.append(f"  {'rule':8} {'resource':24} {'covered':>12}")
    for r in cov["rows"]:
        out.append(f"  {r['rule']:8} {r['resource']:24} "
                   f"{str(r['with_column']) + '/' + str(r['total']):>12}")
    out.append(f"  {'total':8} {'':24} "
               f"{str(cov['with_column']) + '/' + str(cov['total']):>12}")
    out.append("")
    occ = report.get("occurrence_coverage")
    if occ:
        out.append("occurrence coverage (scored, from normalized-findings/v2)")
        out.append(f"  {occ['producer']}: {occ['with_occurrence_id']}/{occ['total']}")
        out.append("")
    d = report["differential"]
    out.append("differential")
    out.append(f"  baseline scored  {d['baseline_scored']}")
    out.append(f"  candidate scored {d['candidate_scored']}")
    out.append(f"  column added     {d['column_added']}   (the one allowed change)")
    out.append("  must be zero:")
    for k, v in sorted(d["must_be_zero"].items()):
        out.append(f"    {k:32} {v}")
    for cat, ex in d["examples"].items():
        out.append(f"  e.g. {cat}:")
        out.extend(f"    {e}" for e in ex)
    out.append("")
    mode = "acceptance (Own.NET#317)" if report.get("acceptance_mode") else "diagnostic"
    out.append(f"gates [{mode}]")
    for k, v in sorted(report["gates"].items()):
        out.append(f"  {'ok ' if v else 'FAIL'}  {k}")
    out.append("")
    out.append("VERDICT: " + ("PASS" if report["pass"] else "FAIL"))
    return "\n".join(out)


def build(baseline: str, candidate: str, baseline_commit: str,
          candidate_commit: str, normalizer_commit: str,
          strips: list[str] | None = None,
          advisory: tuple[str, ...] = DEFAULT_ADVISORY,
          normalized: str | None = None,
          producer: str = "own-check",
          acceptance: bool = False) -> dict[str, Any]:
    if acceptance and not normalized:
        # Exit 2, not FAIL: a missing input is a misconfigured invocation, and a
        # gate that cannot be evaluated must never be reported as one that was.
        raise AcceptanceInputError(
            "--acceptance-ownnet-317 requires --normalized: occurrence coverage is "
            "part of the criterion, and a report that silently omitted it would "
            "print PASS without ever computing an occurrence id.")
    base = read_anchored(baseline, strips, advisory)
    cand = read_anchored(candidate, strips, advisory)
    diff = differential(base, cand)
    cov = column_coverage(cand)
    base_cov = column_coverage(base)
    report: dict[str, Any] = {
        "contract": "anchor-ab/v1",
        "inputs": {
            "baseline": {"sarif": baseline, "digest": sha256_file(baseline),
                         "producer_commit": baseline_commit},
            "candidate": {"sarif": candidate, "digest": sha256_file(candidate),
                          "producer_commit": candidate_commit},
            "normalizer_commit": normalizer_commit,
            "advisory_rules": list(advisory),
        },
        "column_coverage": cov,
        "differential": diff,
    }
    if normalized:
        with open(normalized, encoding="utf-8-sig") as fh:
            report["occurrence_coverage"] = occurrence_coverage(json.load(fh), producer)
    report["baseline_column_coverage"] = base_cov

    # THE VERDICT
    #
    # A clean differential is necessary and nowhere near sufficient. Three ways a
    # PASS could otherwise be printed over a slice that proved nothing:
    #
    #   * the candidate gained no columns at all - caught by requiring
    #     `column_added == candidate_scored`;
    #   * the BASELINE already had columns, so no `null -> column` transformation
    #     ever happened - caught by requiring baseline coverage to be exactly zero.
    #     Full candidate coverage does NOT cover this: it constrains only the
    #     candidate side, and an earlier revision of this comment claimed otherwise;
    #   * neither side ran on the corpus - caught in acceptance mode by pinning the
    #     ledger exactly.
    gates = {
        "differential_clean": diff["clean"],
        "baseline_line_only": base_cov["with_column"] == 0,
        "candidate_fully_columned": (cov["total"] > 0
                                     and cov["with_column"] == cov["total"]),
        "column_added_equals_scored": diff["column_added"] == len(cand),
    }
    if acceptance:
        occ = report.get("occurrence_coverage")
        led = {(r["rule"], r["resource"]): r["total"] for r in cov["rows"]}
        base_led = {(r["rule"], r["resource"]): r["total"] for r in base_cov["rows"]}
        gates.update({
            "baseline_scored_is_ledger": len(base) == STS_317_TOTAL,
            "candidate_scored_is_ledger": len(cand) == STS_317_TOTAL,
            "column_added_is_ledger": diff["column_added"] == STS_317_TOTAL,
            "candidate_ledger_exact": led == STS_317_LEDGER,
            "baseline_ledger_exact": base_led == STS_317_LEDGER,
            "occurrence_producer": bool(occ and occ["producer"] == producer),
            "occurrence_total_is_ledger": bool(occ and occ["total"] == STS_317_TOTAL),
            "occurrence_fully_covered": bool(
                occ and occ["total"] > 0
                and occ["with_occurrence_id"] == occ["total"]),
        })
        report["expected_ledger"] = [
            {"rule": k[0], "resource": k[1], "total": v}
            for k, v in sorted(STS_317_LEDGER.items())]
    report["acceptance_mode"] = bool(acceptance)
    report["gates"] = gates
    report["pass"] = all(gates.values())
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline-commit", required=True,
                    help="producer commit the baseline SARIF was replayed at")
    ap.add_argument("--candidate-commit", required=True)
    ap.add_argument("--normalizer-commit", required=True,
                    help="OwnAudit revision, identical for both sides")
    ap.add_argument("--strip", action="append", default=[])
    ap.add_argument("--advisory-rule", action="append", default=None)
    ap.add_argument("--normalized", help="normalized-findings/v2 payload, for "
                                         "occurrence coverage")
    ap.add_argument("--producer", default="own-check")
    ap.add_argument("--acceptance-ownnet-317", action="store_true",
                    help="gate the Own.NET#317 acceptance criterion: the exact STS "
                         "ledger on BOTH sides, a line-only baseline, and full "
                         "occurrence coverage. Requires --normalized; exits 2 "
                         "without it.")
    ap.add_argument("--json", help="write the machine-readable report here")
    a = ap.parse_args(argv)
    try:
        report = build(a.baseline, a.candidate, a.baseline_commit, a.candidate_commit,
                       a.normalizer_commit, a.strip,
                       tuple(a.advisory_rule) if a.advisory_rule else DEFAULT_ADVISORY,
                       a.normalized, a.producer, a.acceptance_ownnet_317)
    except AcceptanceInputError as e:
        print(f"anchor_ab: {e}", file=sys.stderr)
        return 2
    print(render(report))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
