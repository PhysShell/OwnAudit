#!/usr/bin/env python3
"""The projections a differential run is compared through.

Three views, because "did the output change?" is three different questions and
one answer to all of them is useless:

  A. PATTERN projection - which findings exist, as patterns, and how many of
     each. This is the population question. A producer slice that only moves a
     physical coordinate must leave this projection byte-identical; if a pattern
     appeared, vanished, or changed multiplicity, the change was not what it
     said it was.

  B. PHYSICAL-ANCHOR projection - where each pattern's occurrences sit:
     `(producer, pattern_id, path, start_line, start_column)`. This is the view
     a location change is SUPPOSED to move, and the only one it may move.

  C. COVERAGE metrics - the aggregate ledger: totals, per-producer column
     coverage, ambiguous anchors, locationless findings, occurrence-id coverage,
     and the limitation histogram. Deltas here are the summary a human reads
     first, and two of them (ambiguity, fabricated columns) are gates.

INPUT IS A NORMALIZED PAYLOAD, NOT SARIF
----------------------------------------
Every function here reads a `normalized-findings/v2` document
(`aggregate/normalize.py`). That is deliberate: the normalizer already resolves
`pattern_id`, the physical anchor and the identity limitations from ONE
implementation, so the differ cannot compute identity a second, slightly
different way. A differ with its own private notion of what a finding is would
eventually disagree with the report about what changed.

WHAT THE EMITTED SET DOES NOT CONTAIN
-------------------------------------
`build_payload` drops suppressed and analysis-skipped (advisory) findings from
`findings` and counts them in `coverage` - counted, never hidden. So the pattern
projection here covers the SCORED population only, and the suppression/advisory
populations are compared through their census in the ledger (`suppression_census`
/ `advisory_census`) instead. That is not a gap being papered over: it is the
existing contract, and re-deriving those populations here would mean reading a
field the payload does not carry.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

#: The payload contract this module reads. A differ that silently accepted a
#: different shape would compare two things it had not verified were comparable.
EXPECTED_SCHEMA = "normalized-findings/v2"

#: The limitation token the normalizer stamps when two records in one producer run
#: share an anchor. Imported by value rather than from `identity.occurrence` so
#: this module stays readable standalone; `_selftest` pins the two together.
AMBIGUOUS_ANCHOR = "occurrence-id-unavailable:ambiguous-physical-anchor"

#: The pattern-row attributes carried alongside the count. `pattern_id` is a
#: 16-hex truncation of a SHA-1 over exactly `path`/`rule`/`message`, so these
#: must agree for every record sharing an id - a disagreement is either a
#: truncation collision or a normalizer bug, and both are worth failing on.
PATTERN_ATTRS = ("rule", "path", "message", "category", "category_name", "resource")


class ProjectionError(ValueError):
    """The payload cannot be projected. Raised instead of comparing a guess."""


def _findings(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The findings list, shape-checked.

    A payload is external input to this tool (it comes off a runner, an artifact
    download, or a hand-built fixture), so a wrong schema version or a missing
    identity field is an error here rather than a `KeyError` three frames deeper.
    """
    got = payload.get("schema_version")
    if got != EXPECTED_SCHEMA:
        raise ProjectionError(
            f"expected a {EXPECTED_SCHEMA} payload, got {got!r} - the differ reads "
            f"normalized findings, not raw SARIF")
    records = payload.get("findings")
    if not isinstance(records, list):
        raise ProjectionError("payload 'findings' must be a JSON array")
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise ProjectionError(f"finding #{i} is not an object")
        for key in ("tool", "pattern_id", "physical_anchor", "identity_limitations"):
            if key not in r:
                raise ProjectionError(
                    f"finding #{i} carries no {key!r} - identity is attached by the "
                    f"normalizer; a payload without it was not produced by one")
        if not isinstance(r["physical_anchor"], dict):
            raise ProjectionError(f"finding #{i} 'physical_anchor' must be an object")
    return records


# --------------------------------------------------------------------------- #
# A. Pattern projection                                                       #
# --------------------------------------------------------------------------- #

def pattern_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`{"rows": {key: {...attrs, "count": n}}, "attribute_conflicts": [...]}`.

    The key is `"<producer>\\x1f<pattern_id>"` - a string rather than a tuple so
    the projection round-trips through JSON unchanged (an artifact a human opens
    six weeks later must not need this module to be readable).

    Two producers reporting the same site stay separate rows: they are two
    independent claims, and merging them would let one producer's regression be
    masked by another's finding.
    """
    rows: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for r in _findings(payload):
        key = f"{r['tool']}\x1f{r['pattern_id']}"
        attrs = {k: r.get(k) for k in PATTERN_ATTRS}
        row = rows.get(key)
        if row is None:
            rows[key] = {**attrs, "count": 1}
            continue
        differing = {k: (row[k], attrs[k]) for k in PATTERN_ATTRS if row[k] != attrs[k]}
        if differing:
            # Same producer, same pattern_id, different (path, rule, message)-derived
            # attributes. Either the 16-hex truncation collided or something upstream
            # is minting ids from the wrong fields. Recorded, never merged away.
            conflicts.append({"key": key, "differing": {k: list(v) for k, v in
                                                        sorted(differing.items())}})
        row["count"] += 1
    return {"rows": rows, "attribute_conflicts": conflicts}


def pattern_multiplicity(projection: Mapping[str, Any]) -> dict[str, int]:
    """Just the counts, for the multiplicity comparison."""
    return {k: int(v["count"]) for k, v in projection["rows"].items()}


# --------------------------------------------------------------------------- #
# B. Physical-anchor projection                                               #
# --------------------------------------------------------------------------- #

def anchor_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`{"sites": {site_key: {"path": p, "lines": {line_str: [columns...]}}}}`.

    A SITE is `(producer, pattern_id)`; within a site, occurrences are grouped by
    `start_line`, and each line carries the MULTISET of its columns, sorted with
    `null` first. Grouping this way is what lets the diff say "the same two
    findings on line 42 gained columns 9 and 31" instead of "four anchors
    changed" - two findings on one line is one of the shapes this projection
    exists to describe.

    `path` rides along at the site level even though `pattern_id` already
    determines it: when a path changes, `pattern_id` changes with it, and the
    diff needs the old and new spelling side by side to say so in words rather
    than as an unexplained pattern swap.

    A locationless finding (`start_line` is None) is keyed under `"null"`. It is
    not dropped: a producer that stops reporting a line has regressed, and a
    projection that silently omitted the evidence could not show it.
    """
    sites: dict[str, dict[str, Any]] = {}
    for r in _findings(payload):
        phys = r["physical_anchor"]
        key = f"{r['tool']}\x1f{r['pattern_id']}"
        site = sites.setdefault(key, {"path": phys.get("path"), "lines": {}})
        line = phys.get("start_line")
        site["lines"].setdefault("null" if line is None else str(line), []).append(
            phys.get("start_column"))
    for site in sites.values():
        for line_key, cols in site["lines"].items():
            site["lines"][line_key] = sorted(cols, key=lambda c: (c is not None, c or 0))
    return {"sites": sites}


# --------------------------------------------------------------------------- #
# C. Coverage metrics                                                         #
# --------------------------------------------------------------------------- #

def coverage_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The aggregate ledger for one side of the comparison.

    Reported PER PRODUCER as well as in total, because a column that appeared for
    own-check while quietly disappearing for Roslyn nets out to zero in a single
    total - and the netted number is the one that reads as "nothing happened".
    """
    records = _findings(payload)
    by_producer: dict[str, dict[str, int]] = {}
    limitations: Counter[str] = Counter()
    locationless = 0
    ambiguous = 0
    with_occurrence = 0

    for r in records:
        phys = r["physical_anchor"]
        prod = str(r["tool"])
        b = by_producer.setdefault(prod, {
            "findings": 0, "patterns": 0, "with_start_column": 0,
            "without_start_column": 0, "locationless": 0, "ambiguous_anchors": 0,
            "with_occurrence_id": 0,
        })
        b["findings"] += 1
        has_col = isinstance(phys.get("start_column"), int)
        b["with_start_column" if has_col else "without_start_column"] += 1
        if phys.get("start_line") is None:
            b["locationless"] += 1
            locationless += 1
        limits = r["identity_limitations"] or []
        for lim in limits:
            limitations[str(lim)] += 1
        if AMBIGUOUS_ANCHOR in limits:
            b["ambiguous_anchors"] += 1
            ambiguous += 1
        if r.get("occurrence_id"):
            b["with_occurrence_id"] += 1
            with_occurrence += 1

    patterns_by_producer: dict[str, set[str]] = {}
    for r in records:
        patterns_by_producer.setdefault(str(r["tool"]), set()).add(str(r["pattern_id"]))
    for prod, pats in patterns_by_producer.items():
        by_producer[prod]["patterns"] = len(pats)

    cov = payload.get("coverage") or {}
    return {
        "total_findings": len(records),
        "pattern_count": len({f"{r['tool']}\x1f{r['pattern_id']}" for r in records}),
        "locationless": locationless,
        "ambiguous_anchors": ambiguous,
        "with_occurrence_id": with_occurrence,
        "without_occurrence_id": len(records) - with_occurrence,
        "identity_limitations": dict(limitations.most_common()),
        "by_producer": by_producer,
        # The suppressed / analysis-skipped populations are NOT in `findings` by
        # contract, so their census is read straight off the ledger. Absent keys
        # read as 0 rather than as an error: a payload from a corpus with nothing
        # suppressed legitimately has nothing to report.
        "suppression_census": {
            "suppressed": int(cov.get("suppressed", 0) or 0),
            "suppressed_by": dict(cov.get("suppressed_by") or {}),
        },
        "advisory_census": {
            "analysis_skipped": int(cov.get("analysis_skipped", 0) or 0),
            "analysis_skipped_by": dict(cov.get("analysis_skipped_by") or {}),
        },
    }


# --------------------------------------------------------------------------- #
# Fabrication smells - checks that are not diffs                              #
# --------------------------------------------------------------------------- #

def uniform_column_producers(payload: Mapping[str, Any]) -> dict[str, int]:
    """Producers whose EVERY reported column is the same value, keyed to that value.

    A producer that starts emitting `startColumn: 1` for every finding has not
    learned where its findings are; it has learned to print a number. The anchor
    then looks richer while discriminating exactly as poorly as before, which is
    the failure mode a naive "columns appeared, ship it" check rewards.

    Only producers with at least two columns are considered - a corpus slice with
    one finding cannot distinguish "uniform" from "correct", and calling it
    uniform would fail honest single-finding fixtures.
    """
    seen: dict[str, set[int]] = {}
    counts: Counter[str] = Counter()
    for r in _findings(payload):
        col = r["physical_anchor"].get("start_column")
        if isinstance(col, int):
            prod = str(r["tool"])
            seen.setdefault(prod, set()).add(col)
            counts[prod] += 1
    return {prod: next(iter(cols)) for prod, cols in seen.items()
            if len(cols) == 1 and counts[prod] > 1}


def column_collisions(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Sites where DISTINCT patterns at one `(producer, path, line)` share a column.

    Two different findings on one line are the case a column is supposed to tell
    apart. If they came back with the same column, the coordinate is decoration:
    it costs a schema field and buys no discrimination. Reported with the
    colliding pattern ids so the offending pair is nameable, not just counted.
    """
    buckets: dict[tuple[str, str, int, int], set[str]] = {}
    for r in _findings(payload):
        phys = r["physical_anchor"]
        line, col = phys.get("start_line"), phys.get("start_column")
        if not isinstance(line, int) or not isinstance(col, int):
            continue
        buckets.setdefault((str(r["tool"]), str(phys.get("path")), line, col),
                           set()).add(str(r["pattern_id"]))
    return [
        {"producer": prod, "path": path, "start_line": line, "start_column": col,
         "pattern_ids": sorted(pats)}
        for (prod, path, line, col), pats in sorted(buckets.items())
        if len(pats) > 1
    ]


def _selftest() -> int:
    """`PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/project.py --selftest`"""
    from identity.occurrence import LIMIT_AMBIGUOUS_ANCHOR

    fails: list[str] = []
    if LIMIT_AMBIGUOUS_ANCHOR != AMBIGUOUS_ANCHOR:
        fails.append(f"ambiguity token drifted: {LIMIT_AMBIGUOUS_ANCHOR!r} vs "
                     f"{AMBIGUOUS_ANCHOR!r}")
    for f in fails:
        print(f"FAIL: {f}")
    print(f"corpusdiff/project selftest: {'OK' if not fails else 'FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
    print("usage: PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/project.py --selftest")
    raise SystemExit(2)
