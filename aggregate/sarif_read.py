#!/usr/bin/env python3
"""SARIF -> raw findings: the reader `aggregate/normalize.py` folds every tool through.

Vendored from the deprecated `Own.NET/audit/`, where `normalize.py` borrowed
`parse_sarif`/`norm_path` from `scripts/oracle_compare.py` across the repo with a
`sys.path.insert` and a comment promising it "gets vendored on lift-out". This is
that vendoring: OwnAudit reads SARIF with its own code and never imports a Python
module out of a neighbouring Own.NET checkout in production.

WHAT WAS AND WAS NOT CARRIED OVER
---------------------------------
The oracle's reader also classified each result into `leak` / `use-after` /
`double` / `other` (`cls`) for the three-way oracle diff, and precomputed a
basename `fkey` for cross-tool matching. Normalization uses **neither**: it says
so out loud ("we ignore the oracle's leak/other cls and apply our own richer
taxonomy instead") and `AuditFinding` computes its own `fkey`. Carrying them here
would have meant vendoring the oracle's rule families as a second, unused source
of truth about what counts as a leak - so this reader stops at the five fields
normalization actually reads: tool, path, line, rule, message.

The parse itself is unchanged, deliberately. `norm_path`'s longest-prefix strip and
`_first_location`'s "first location with a uri wins" are what the recorded
`sts_audit/findings.json` was produced with; `aggregate/tests/test_normalize.py`
pins the whole pipeline byte-for-byte against a payload the reference
implementation generated.

RESULTS WITH NO USABLE LOCATION (#57)
-------------------------------------
A SARIF result whose every location lacks an `artifactLocation.uri` cannot become
a finding here: the whole downstream identity chain - `physical_anchor`, then
`pattern_id` / `occurrence_id`, then the ambiguity census - is built on a real
`(path, line, column)`. Substituting `path: ""` / `line: 0` would not preserve
the result, it would fabricate a coordinate the producer never reported and let
it enter identity as if it had.

So such a result is still not a finding. What changed is that it is no longer
*invisible*: the reader counts it, by rule, and `aggregate/normalize.py` carries
that count into the coverage ledger as `no_physical_location` /
`no_physical_location_by`. Every other lossy path in this pipeline already
reports itself - an unmapped rule lands in `uncategorized_rules`, a third-party
hit in `suppressed_by`, an analysis diagnostic in `analysis_skipped_by` - and
this was the one place a result could leave the pipeline with no counter and no
reason. On the recorded STS corpus that silence covered 1 121 of 74 518 results.

Deciding what those results *are* - project- or build-level diagnostics with no
file to point at, most likely - and whether they deserve a representation of
their own is a separate question with its own identity contract. This slice only
makes their absence accountable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class RawFinding:
    """One SARIF result, read but not yet categorized."""

    tool: str        # "own-check" | "codeql" | "infersharp" | "roslyn" | ...
    path: str        # normalized, repo-relative where possible
    line: int        # 0 when the result carries no startLine
    rule: str        # OWN001 / cs/local-not-disposed / PULSE_RESOURCE_LEAK / ...
    message: str
    #: `region.startColumn`, or None when the producer did not report one.
    #: NULLABLE ON PURPOSE (Own.NET#266 slice 1B): a missing column stays missing.
    #: In the recorded STS corpus own-check emits a column for exactly 0 of its
    #: 613 results while CodeQL, Infer# and Roslyn emit one for all of theirs, so
    #: this is the common case, not an edge. It does not enter the normalized
    #: record's ten legacy fields; it feeds the physical anchor.
    column: int | None = None


def norm_path(raw: str, strips: list[str]) -> str:
    """Normalize a finding path: forward slashes, no `file://` scheme, and the
    LONGEST matching `--strip` prefix removed.

    Longest-first matters: `--strip` is passed several overlapping spellings of the
    same worktree (bare leaf, absolute, leading-slash absolute), and stripping the
    shortest would leave a path fragment glued to the front of every finding.
    """
    p = raw.replace("\\", "/")
    for scheme in ("file://", "file:"):
        if p.startswith(scheme):
            p = p[len(scheme):]
    prefixes = sorted((s.replace("\\", "/").rstrip("/") for s in strips),
                      key=len, reverse=True)
    for pre in prefixes:
        if pre and p.startswith(pre):
            p = p[len(pre):]
            break
    if p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _first_location(res: dict[str, Any]) -> tuple[str, int, int | None] | None:
    """The primary (uri, startLine, startColumn) of a result, or None if it has none.

    The first location carrying an artifact uri wins; a missing/!int `startLine`
    reads as 0 rather than failing, because a locationless line is a presentation
    problem and dropping the whole finding for it would be a reporting lie.

    `startColumn` is different: it reads as **None**, never 0 and never 1. SARIF
    columns are 1-based, so there is no in-band value that means "not reported",
    and a substituted 1 would be indistinguishable from a real first-column
    finding - a fabricated coordinate that the physical anchor would then treat
    as evidence.
    """
    for loc in res.get("locations", []):
        phys = loc.get("physicalLocation") or {}
        uri = (phys.get("artifactLocation") or {}).get("uri")
        if not uri:
            continue
        region = phys.get("region") or {}
        line = region.get("startLine")
        col = region.get("startColumn")
        return (uri,
                line if isinstance(line, int) else 0,
                col if isinstance(col, int) and col >= 1 else None)
    return None


def driver_version(data: dict[str, Any]) -> str | None:
    """The version the SARIF driver declares for itself, or None.

    `semanticVersion` is preferred over `version` because it is the one SARIF
    defines as machine-comparable. Only CodeQL declares anything at all in the
    recorded corpus; the rest report nothing, and nothing is what they get - a
    version invented here would be provenance about the reader, not the producer.
    """
    for run in data.get("runs", []):
        drv = (run.get("tool") or {}).get("driver") or {}
        for key in ("semanticVersion", "version"):
            v = drv.get(key)
            if isinstance(v, str) and v:
                return v
    return None


@dataclass
class SarifReadResult:
    """One SARIF log, read: the findings, plus what reading it cost.

    The read stats have to travel with the findings because they cannot be
    recovered afterwards. `coverage()` runs over `AuditFinding`s, and by then the
    locationless results are simply not there - their number is not derivable
    from what survived. Recomputing it later by re-reading the files would also
    make the ledger's honesty depend on a second pass agreeing with the first.
    """

    findings: list[RawFinding]
    #: Results skipped because no location carried an `artifactLocation.uri`.
    no_physical_location: int
    #: Those results by `ruleId`. A result with no rule at all is counted under
    #: `""`, matching how `uncategorized_rules` already spells an empty ruleId -
    #: a made-up sentinel would be a second vocabulary for the same absence.
    no_physical_location_by_rule: dict[str, int]
    #: What the driver declares about itself, or None. See `driver_version`.
    driver_version: str | None


def read_sarif(text: str, tool: str, strips: list[str]) -> SarifReadResult:
    """Parse a SARIF log (own-check, CodeQL, Infer#, Roslyn) with its read stats.

    The detailed entry point. `parse_sarif` and `parse_sarif_with_driver` are the
    narrow views onto it and keep their signatures, so nothing that only wants
    findings has to learn about the ledger.
    """
    return _read(json.loads(text), tool, strips)


def parse_sarif_with_driver(text: str, tool: str,
                            strips: list[str]) -> tuple[list[RawFinding], str | None]:
    """`parse_sarif`, plus the driver version, from a SINGLE parse.

    Separate entry point rather than a changed signature: the corpus SARIF runs to
    35 MB a file, and re-reading one just to look at `tool.driver` would double the
    cost of the whole stage for six bytes of metadata.
    """
    r = _read(json.loads(text), tool, strips)
    return r.findings, r.driver_version


def parse_sarif(text: str, tool: str, strips: list[str]) -> list[RawFinding]:
    """Parse a SARIF log (own-check, CodeQL, Infer#, Roslyn) into RawFindings."""
    return _read(json.loads(text), tool, strips).findings


def _read(data: dict[str, Any], tool: str, strips: list[str]) -> SarifReadResult:
    out: list[RawFinding] = []
    lost: dict[str, int] = {}
    for run in data.get("runs", []):
        for res in run.get("results", []):
            rule = res.get("ruleId") or (res.get("rule") or {}).get("id") or ""
            msg = ((res.get("message") or {}).get("text") or "").strip()
            loc = _first_location(res)
            if loc is None:
                # Not a finding - there is no anchor to make one from - but it
                # WAS a result, and the ledger is entitled to know that.
                lost[rule] = lost.get(rule, 0) + 1
                continue
            uri, line, col = loc
            out.append(RawFinding(tool, norm_path(uri, strips), line, rule, msg, col))
    return SarifReadResult(findings=out,
                           no_physical_location=sum(lost.values()),
                           no_physical_location_by_rule=lost,
                           driver_version=driver_version(data))
