#!/usr/bin/env python3
"""The differential comparison itself: two normalized payloads -> one verdict.

Reads the projections from `corpusdiff.project`, classifies every difference
against a `corpus-delta/v1` expectation (`corpusdiff.delta`), and emits a
machine-readable report plus a short Markdown verdict a human can read on a PR.

THE SHAPE OF THE ANSWER
-----------------------
Every difference becomes one CHANGE record with a `kind`, the detail that makes
it locatable, and a status: `allowed` (an expectation signed it off) or
`violation`. Nothing is dropped on the way - an unclassifiable difference is a
violation, never a silence, because the failure mode this whole apparatus exists
to prevent is a real regression that produced no output.

Separately, an expectation may PIN an aggregate as unchanged. A pin failure is
reported apart from the change list: "a column moved and that was allowed" and
"the expectation said the column population would not move, and it did" are
different statements about the same run, and collapsing them would hide the
second behind the first.

WHY PATH CHANGES ARE RECONSTRUCTED RATHER THAN OBSERVED
------------------------------------------------------
`pattern_id` is a hash over `(path, rule, message)`, so a finding that moves file
does not show up as "the path changed" - it shows up as one pattern vanishing and
an unrelated one appearing. That reading is technically true and practically
useless. So before reporting orphans, removed and new patterns that agree on
`(producer, rule, message)` are paired back up and reported as a `path_change`,
with both spellings in the record. Only genuinely unpaired orphans are reported
as `removed_pattern` / `new_pattern`.

WHY `occurrence_id` IS ABSENT FROM EVERY COMPARISON
--------------------------------------------------
It hashes `producer_run_id`, so two real runs differ by contract. Comparing them
would report the contract working as a total regression on every single run. What
IS compared is the coverage - how many records earned an id, and which
limitations blocked the rest.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import SCHEMA_VERSION
from .delta import STRICT, Expectation
from .project import (
    anchor_projection, column_collisions, coverage_metrics, pattern_multiplicity,
    pattern_projection, uniform_column_producers,
)

#: How many change records of one kind the Markdown rendering lists in full. The
#: rest are counted, and the count is stated out loud - a truncation that does not
#: announce itself reads as "that was all of them".
MARKDOWN_SAMPLE = 10


def _split_key(key: str) -> tuple[str, str]:
    """`"<producer>\\x1f<pattern_id>"` -> its two halves."""
    producer, _, pattern = key.partition("\x1f")
    return producer, pattern


def _transition(before: int | None, after: int | None) -> str | None:
    """The `corpus-delta/v1` transition name for one column move, or None if it
    did not move."""
    if before == after:
        return None
    if before is None:
        return "null-to-positive-integer"
    if after is None:
        return "positive-integer-to-null"
    return "positive-integer-to-positive-integer"


def _line_counts(site: Mapping[str, Any]) -> dict[str, int]:
    """`{line_key: occurrence count}` for one anchor site.

    Counts, not a set of lines: two findings on line 42 collapsing into one is a
    real move that a set comparison reads as no change at all.
    """
    return {line: len(cols) for line, cols in site["lines"].items()}


# --------------------------------------------------------------------------- #
# Pattern projection diff                                                     #
# --------------------------------------------------------------------------- #

def _pattern_changes(base: Mapping[str, Any],
                     cand: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    b_rows, c_rows = base["rows"], cand["rows"]
    removed = sorted(set(b_rows) - set(c_rows))
    added = sorted(set(c_rows) - set(b_rows))

    # Pair orphans that agree on (producer, rule, message) back into a path change.
    # Keyed on a list so an ambiguous pairing (two files gaining the same finding)
    # stays visible as two orphans rather than being paired arbitrarily.
    def ident(key: str, rows: Mapping[str, Any]) -> tuple[str, Any, Any]:
        return (_split_key(key)[0], rows[key]["rule"], rows[key]["message"])

    b_index: dict[tuple[str, Any, Any], list[str]] = {}
    for key in removed:
        b_index.setdefault(ident(key, b_rows), []).append(key)
    c_index: dict[tuple[str, Any, Any], list[str]] = {}
    for key in added:
        c_index.setdefault(ident(key, c_rows), []).append(key)

    paired_b: set[str] = set()
    paired_c: set[str] = set()
    for sig, b_keys in sorted(b_index.items()):
        c_keys = c_index.get(sig, [])
        # Only an unambiguous 1:1 pairing is a path change. Anything else is two
        # honest orphans; inventing a pairing would name the wrong file as the
        # source of the move.
        if len(b_keys) != 1 or len(c_keys) != 1:
            continue
        b_key, c_key = b_keys[0], c_keys[0]
        paired_b.add(b_key)
        paired_c.add(c_key)
        changes.append({
            "kind": "path_change",
            "producer": sig[0],
            "rule": b_rows[b_key]["rule"],
            "from_path": b_rows[b_key]["path"],
            "to_path": c_rows[c_key]["path"],
            "from_pattern_id": _split_key(b_key)[1],
            "to_pattern_id": _split_key(c_key)[1],
        })

    for key in removed:
        if key in paired_b:
            continue
        producer, pattern = _split_key(key)
        row = b_rows[key]
        changes.append({"kind": "removed_pattern", "producer": producer,
                        "pattern_id": pattern, "rule": row["rule"],
                        "path": row["path"], "message": row["message"],
                        "count": row["count"]})
    for key in added:
        if key in paired_c:
            continue
        producer, pattern = _split_key(key)
        row = c_rows[key]
        changes.append({"kind": "new_pattern", "producer": producer,
                        "pattern_id": pattern, "rule": row["rule"],
                        "path": row["path"], "message": row["message"],
                        "count": row["count"]})

    b_mult, c_mult = pattern_multiplicity(base), pattern_multiplicity(cand)
    for key in sorted(set(b_mult) & set(c_mult)):
        if b_mult[key] != c_mult[key]:
            producer, pattern = _split_key(key)
            changes.append({"kind": "multiplicity_change", "producer": producer,
                            "pattern_id": pattern, "path": b_rows[key]["path"],
                            "rule": b_rows[key]["rule"],
                            "before": b_mult[key], "after": c_mult[key]})

    # An attribute conflict on EITHER side is reported: a truncation collision that
    # only exists in the baseline still makes that side's projection unreliable, and
    # a differ that only checked the candidate would compare against a known-bad
    # reference without saying so.
    for side, proj in (("baseline", base), ("candidate", cand)):
        for conflict in proj["attribute_conflicts"]:
            producer, pattern = _split_key(conflict["key"])
            changes.append({"kind": "pattern_attribute_change", "side": side,
                            "producer": producer, "pattern_id": pattern,
                            "differing": conflict["differing"]})
    return changes


# --------------------------------------------------------------------------- #
# Physical-anchor projection diff                                             #
# --------------------------------------------------------------------------- #

def _anchor_changes(base: Mapping[str, Any],
                    cand: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Anchor movement for sites present on BOTH sides.

    Sites that exist on one side only are already reported at the pattern level
    (as a new/removed pattern or a path change); repeating them here as anchor
    movement would double-count one event and inflate the violation total.
    """
    changes: list[dict[str, Any]] = []
    b_sites, c_sites = base["sites"], cand["sites"]
    for key in sorted(set(b_sites) & set(c_sites)):
        producer, pattern = _split_key(key)
        b_site, c_site = b_sites[key], c_sites[key]
        b_counts, c_counts = _line_counts(b_site), _line_counts(c_site)
        if b_counts != c_counts:
            changes.append({
                "kind": "line_change", "producer": producer, "pattern_id": pattern,
                "path": c_site["path"],
                "before": dict(sorted(b_counts.items())),
                "after": dict(sorted(c_counts.items())),
            })
            # The columns on a line that moved are not comparable - there is no
            # occurrence-to-occurrence correspondence left to compare them through.
            # Reporting a column transition on top of the line move would be an
            # invented pairing.
            continue
        for line in sorted(b_site["lines"]):
            for before, after in zip(b_site["lines"][line], c_site["lines"][line]):
                transition = _transition(before, after)
                if transition is None:
                    continue
                changes.append({
                    "kind": "start_column_change", "producer": producer,
                    "pattern_id": pattern, "path": c_site["path"],
                    "start_line": None if line == "null" else int(line),
                    "before": before, "after": after, "transition": transition,
                })
    return changes


# --------------------------------------------------------------------------- #
# Coverage + fabrication diff                                                 #
# --------------------------------------------------------------------------- #

def _coverage_delta(base: Mapping[str, Any], cand: Mapping[str, Any]) -> dict[str, Any]:
    """The scalar deltas, plus each producer's column-coverage move.

    `occurrence_coverage` is reported and never asserted equal: for the physical
    anchor slice it MAY legitimately stay flat (a corpus run with no provenance
    manifest earns no ids at all, and a line-only anchor that was already unique
    earns one either way). Only a DECREASE is a change kind.
    """
    scalars = ("total_findings", "pattern_count", "locationless", "ambiguous_anchors",
               "with_occurrence_id", "without_occurrence_id")
    delta = {k: int(cand[k]) - int(base[k]) for k in scalars}
    producers: dict[str, dict[str, int]] = {}
    for prod in sorted(set(base["by_producer"]) | set(cand["by_producer"])):
        b = base["by_producer"].get(prod, {})
        c = cand["by_producer"].get(prod, {})
        producers[prod] = {
            k: int(c.get(k, 0)) - int(b.get(k, 0))
            for k in ("findings", "patterns", "with_start_column",
                      "without_start_column", "locationless", "ambiguous_anchors",
                      "with_occurrence_id")
        }
    return {"scalars": delta, "by_producer": producers}


def _coverage_changes(base: Mapping[str, Any],
                      cand: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if cand["ambiguous_anchors"] > base["ambiguous_anchors"]:
        changes.append({"kind": "ambiguity_increase",
                        "before": base["ambiguous_anchors"],
                        "after": cand["ambiguous_anchors"]})
    if cand["locationless"] > base["locationless"]:
        changes.append({"kind": "locationless_increase",
                        "before": base["locationless"], "after": cand["locationless"]})
    if cand["with_occurrence_id"] < base["with_occurrence_id"]:
        changes.append({"kind": "occurrence_coverage_decrease",
                        "before": base["with_occurrence_id"],
                        "after": cand["with_occurrence_id"]})
    if base["suppression_census"] != cand["suppression_census"]:
        changes.append({"kind": "suppression_census_change",
                        "before": base["suppression_census"],
                        "after": cand["suppression_census"]})
    if base["advisory_census"] != cand["advisory_census"]:
        changes.append({"kind": "advisory_census_change",
                        "before": base["advisory_census"],
                        "after": cand["advisory_census"]})
    return changes


def _fabrication_changes(base_payload: Mapping[str, Any],
                         cand_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The two shapes that make a column look like information without being any.

    Both are reported only when the CANDIDATE introduces them: a corpus whose
    baseline already collides is a pre-existing condition this run did not cause,
    and failing a producer PR for it would make the gate un-passable for reasons
    outside the diff.
    """
    changes: list[dict[str, Any]] = []
    b_uniform = uniform_column_producers(base_payload)
    for producer, value in sorted(uniform_column_producers(cand_payload).items()):
        if b_uniform.get(producer) == value:
            continue
        changes.append({"kind": "fabricated_column_uniform", "producer": producer,
                        "start_column": value})

    b_collisions = {(c["producer"], c["path"], c["start_line"], c["start_column"])
                    for c in column_collisions(base_payload)}
    for coll in column_collisions(cand_payload):
        sig = (coll["producer"], coll["path"], coll["start_line"], coll["start_column"])
        if sig in b_collisions:
            continue
        changes.append({"kind": "fabricated_column_collision", **coll})
    return changes


# --------------------------------------------------------------------------- #
# Classification + verdict                                                    #
# --------------------------------------------------------------------------- #

def _classify(change: dict[str, Any], expect: Expectation) -> dict[str, Any]:
    """Stamp one change with `status` and the reason for it."""
    kind = change["kind"]
    if expect.forbids(kind):
        return {**change, "status": "violation",
                "why": f"{kind} is listed in the expectation's 'forbidden'"}
    if expect.permits(kind, change.get("producer"), change.get("transition")):
        return {**change, "status": "allowed",
                "why": f"allowed_changes permits {change.get('transition')} of "
                       f"{change.get('producer')}'s start_column"}
    if expect.strict:
        return {**change, "status": "violation",
                "why": "no corpus-delta/v1 expectation was given, so no output "
                       "change is signed off"}
    return {**change, "status": "violation",
            "why": f"the expectation does not permit {kind}"}


def _pin_failures(expect: Expectation, changes: list[dict[str, Any]],
                  base: Mapping[str, Any], cand: Mapping[str, Any],
                  base_patterns: Mapping[str, Any],
                  cand_patterns: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Aggregates the expectation pinned as unchanged, that moved anyway.

    Checked against the projections rather than inferred from the change list, so
    a pin still fails if some future change kind stops being emitted.
    """
    out: list[dict[str, Any]] = []
    if expect.pins("pattern_population"):
        b_keys, c_keys = set(base_patterns["rows"]), set(cand_patterns["rows"])
        if b_keys != c_keys:
            out.append({"pin": "pattern_population",
                        "detail": {"removed": len(b_keys - c_keys),
                                   "added": len(c_keys - b_keys)}})
    if expect.pins("finding_count") and base["total_findings"] != cand["total_findings"]:
        out.append({"pin": "finding_count",
                    "detail": {"before": base["total_findings"],
                               "after": cand["total_findings"]}})
    if expect.pins("start_line"):
        moved = [c for c in changes if c["kind"] == "line_change"]
        if moved:
            out.append({"pin": "start_line", "detail": {"sites_moved": len(moved)}})
    if expect.pins("start_column"):
        moved = [c for c in changes if c["kind"] == "start_column_change"]
        if moved:
            out.append({"pin": "start_column",
                        "detail": {"occurrences_moved": len(moved)}})
    return out


def compare(baseline: Mapping[str, Any], candidate: Mapping[str, Any],
            expect: Expectation | None = None) -> dict[str, Any]:
    """The whole comparison: projections, changes, pins, verdict."""
    expect = expect or STRICT
    b_patterns, c_patterns = pattern_projection(baseline), pattern_projection(candidate)
    b_anchors, c_anchors = anchor_projection(baseline), anchor_projection(candidate)
    b_cov, c_cov = coverage_metrics(baseline), coverage_metrics(candidate)

    raw = (_pattern_changes(b_patterns, c_patterns)
           + _anchor_changes(b_anchors, c_anchors)
           + _coverage_changes(b_cov, c_cov)
           + _fabrication_changes(baseline, candidate))
    changes = [_classify(c, expect) for c in raw]
    pins = _pin_failures(expect, changes, b_cov, c_cov, b_patterns, c_patterns)

    violations = [c for c in changes if c["status"] == "violation"]
    allowed = [c for c in changes if c["status"] == "allowed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": "fail" if violations or pins else "pass",
        "expectation": expect.to_dict(),
        "totals": {
            "changes": len(changes), "violations": len(violations),
            "allowed": len(allowed), "pin_failures": len(pins),
            "by_kind": _by_kind(changes),
        },
        "coverage": {"baseline": b_cov, "candidate": c_cov,
                     "delta": _coverage_delta(b_cov, c_cov)},
        "pin_failures": pins,
        "violations": violations,
        "allowed": allowed,
    }


def _by_kind(changes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in changes:
        bucket = out.setdefault(c["kind"], {"allowed": 0, "violation": 0})
        bucket[c["status"]] += 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# Markdown rendering                                                          #
# --------------------------------------------------------------------------- #

def _describe(change: Mapping[str, Any]) -> str:
    kind = change["kind"]
    if kind == "start_column_change":
        return (f"`{change['path']}:{change['start_line']}` "
                f"{change['before']} -> {change['after']} ({change['producer']})")
    if kind == "line_change":
        return (f"`{change['path']}` lines {change['before']} -> {change['after']} "
                f"({change['producer']})")
    if kind == "path_change":
        return (f"`{change['from_path']}` -> `{change['to_path']}` "
                f"[{change['rule']}] ({change['producer']})")
    if kind in ("new_pattern", "removed_pattern"):
        return (f"`{change['path']}` [{change['rule']}] x{change['count']} "
                f"({change['producer']})")
    if kind == "multiplicity_change":
        return (f"`{change['path']}` [{change['rule']}] "
                f"x{change['before']} -> x{change['after']} ({change['producer']})")
    if kind == "fabricated_column_collision":
        return (f"`{change['path']}:{change['start_line']}` column "
                f"{change['start_column']} shared by "
                f"{len(change['pattern_ids'])} distinct patterns ({change['producer']})")
    if kind == "fabricated_column_uniform":
        return (f"{change['producer']} reports start_column "
                f"{change['start_column']} for every finding")
    return ", ".join(f"{k}={v!r}" for k, v in sorted(change.items())
                     if k not in ("kind", "status", "why"))


def render_markdown(report: Mapping[str, Any]) -> str:
    """A short verdict for a PR comment or a job summary.

    The machine report is the artifact of record; this is the part a human reads
    in ten seconds. It states the verdict, the coverage move, and the violations -
    and when it lists only a sample, it says how many it did not list.
    """
    cov = report["coverage"]
    delta = cov["delta"]["scalars"]
    totals = report["totals"]
    ok = report["verdict"] == "pass"
    lines = [
        f"## Corpus differential: {'PASS' if ok else 'FAIL'}",
        "",
        f"- findings: {cov['baseline']['total_findings']} -> "
        f"{cov['candidate']['total_findings']} ({delta['total_findings']:+d})",
        f"- patterns: {cov['baseline']['pattern_count']} -> "
        f"{cov['candidate']['pattern_count']} ({delta['pattern_count']:+d})",
        f"- ambiguous anchors: {cov['baseline']['ambiguous_anchors']} -> "
        f"{cov['candidate']['ambiguous_anchors']} ({delta['ambiguous_anchors']:+d})",
        f"- locationless: {cov['baseline']['locationless']} -> "
        f"{cov['candidate']['locationless']} ({delta['locationless']:+d})",
        f"- with occurrence_id: {cov['baseline']['with_occurrence_id']} -> "
        f"{cov['candidate']['with_occurrence_id']} "
        f"({delta['with_occurrence_id']:+d})",
        "",
        "### start_column coverage by producer",
        "",
        "| producer | before | after | delta |",
        "| --- | --- | --- | --- |",
    ]
    producers = sorted(set(cov["baseline"]["by_producer"])
                       | set(cov["candidate"]["by_producer"]))
    for prod in producers:
        before = cov["baseline"]["by_producer"].get(prod, {}).get("with_start_column", 0)
        after = cov["candidate"]["by_producer"].get(prod, {}).get("with_start_column", 0)
        lines.append(f"| {prod} | {before} | {after} | {after - before:+d} |")

    lines += ["", f"### Changes: {totals['changes']} "
                  f"({totals['allowed']} allowed, {totals['violations']} violations, "
                  f"{totals['pin_failures']} pin failures)", ""]
    for kind, counts in totals["by_kind"].items():
        lines.append(f"- `{kind}`: {counts['allowed']} allowed, "
                     f"{counts['violation']} violations")
    if not totals["by_kind"]:
        lines.append("- no differences in any projection")

    if report["pin_failures"]:
        lines += ["", "### Pin failures", ""]
        for pin in report["pin_failures"]:
            lines.append(f"- `unchanged.{pin['pin']}` was pinned but moved: "
                         f"{pin['detail']}")

    if report["violations"]:
        lines += ["", "### Violations", ""]
        by_kind: dict[str, list[Mapping[str, Any]]] = {}
        for v in report["violations"]:
            by_kind.setdefault(v["kind"], []).append(v)
        for kind, items in sorted(by_kind.items()):
            lines.append(f"**{kind}** ({len(items)}) - {items[0]['why']}")
            for item in items[:MARKDOWN_SAMPLE]:
                lines.append(f"  - {_describe(item)}")
            if len(items) > MARKDOWN_SAMPLE:
                lines.append(f"  - ... and {len(items) - MARKDOWN_SAMPLE} more not "
                             f"listed here; the full set is in the JSON report")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
