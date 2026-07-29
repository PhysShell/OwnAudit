"""`corpusdiff` - differential comparison of two producer runs over one corpus.

OwnAudit compares corpora; Own.NET produces SARIF. This package is the compare
half, and it lives here rather than in Own.NET's core for the reason the boundary
was drawn in the first place: a leak checker that also grades its own regressions
is a Swiss army knife, and the grader stops being independent evidence.

WHAT IT IS FOR
--------------
A producer change that deliberately alters output - a new physical anchor, a
richer location, a renamed message - cannot be gated by "the bytes are equal".
It also must not be gated by "differences are fine", which is not a test but a
signed permission slip for the program to surprise you. The middle ground is to
compare PROJECTIONS: several deliberately partial views of a run, each with its
own expectation about what may and may not move.

`corpusdiff.project` builds the projections, `corpusdiff.delta` reads the
checked-in expectation (`corpus-delta/v1`), and `corpusdiff.diff` renders the
verdict. `corpusdiff.__main__` is the CLI the CI jobs and the long corpus runs
both call.

WHY `occurrence_id` IS NEVER COMPARED DIRECTLY
----------------------------------------------
`finding-occurrence/v1` hashes `producer_run_id` into the id ON PURPOSE - it
identifies a physical finding IN A RUN. Two genuine runs are two runs, so their
occurrence ids differ by contract. Diffing them would report the contract working
as designed as a total regression, every single time. What is comparable is the
occurrence COVERAGE (how many records earned an id, and which limitations
blocked the rest), and that is a coverage metric, not an identity match.
"""

from __future__ import annotations

#: The report document this package emits.
SCHEMA_VERSION = "corpus-differential/v1"

__all__ = ["SCHEMA_VERSION"]
