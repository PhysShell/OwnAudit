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

KNOWN GAP, PRESERVED ON PURPOSE
-------------------------------
A SARIF result with no usable location is skipped silently and counted nowhere.
That is the reference behaviour and it stays here so the parity fixture means
something; it is a real hole in the coverage ledger (which otherwise refuses to
lose a finding without saying so) and it is tracked separately, not fixed under a
port that claims byte-identical output.
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


def parse_sarif_with_driver(text: str, tool: str,
                            strips: list[str]) -> tuple[list[RawFinding], str | None]:
    """`parse_sarif`, plus the driver version, from a SINGLE parse.

    Separate entry point rather than a changed signature: the corpus SARIF runs to
    35 MB a file, and re-reading one just to look at `tool.driver` would double the
    cost of the whole stage for six bytes of metadata.
    """
    data = json.loads(text)
    return _results(data, tool, strips), driver_version(data)


def parse_sarif(text: str, tool: str, strips: list[str]) -> list[RawFinding]:
    """Parse a SARIF log (own-check, CodeQL, Infer#, Roslyn) into RawFindings."""
    return _results(json.loads(text), tool, strips)


def _results(data: dict[str, Any], tool: str, strips: list[str]) -> list[RawFinding]:
    out: list[RawFinding] = []
    for run in data.get("runs", []):
        for res in run.get("results", []):
            rule = res.get("ruleId") or (res.get("rule") or {}).get("id") or ""
            msg = ((res.get("message") or {}).get("text") or "").strip()
            loc = _first_location(res)
            if loc is None:
                continue
            uri, line, col = loc
            out.append(RawFinding(tool, norm_path(uri, strips), line, rule, msg, col))
    return out
