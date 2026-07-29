#!/usr/bin/env python3
"""`corpus-delta/v1` - the checked-in expectation for an INTENTIONAL output change.

A producer slice that deliberately changes output needs its intent written down
where CI can read it, or the differential gate degrades into one of the two
useless extremes:

  * "nothing may differ" - correct until the first deliberate improvement, then
    permanently red, then disabled by whoever is tired of it;
  * "differences are fine" - green forever, including on the day a finding
    silently disappears.

So the expectation states, per slice, exactly which projection field may move,
for which producer, and through which transition. Everything else is a
violation. The file is data, reviewed in the same PR as the change it describes.

    {
      "schema": "corpus-delta/v1",
      "unchanged":       {"pattern_population": true, "finding_count": true,
                          "start_line": true},
      "allowed_changes": [{"field": "start_column", "producer": "own-check",
                           "transition": "null-to-positive-integer"}],
      "forbidden":       ["new_pattern", "removed_pattern", "path_change",
                          "line_change", "ambiguity_increase"]
    }

THERE IS NO `allow_any_difference`
---------------------------------
It is rejected by name, with its own error message, because it is the shape every
one of these files decays into under deadline pressure. A test that accepts any
difference has stopped being a test and become written permission for the program
to surprise you in any way it likes; the honest version of that decision is to
delete the job, where its absence is at least visible in the workflow file.

WHY `forbidden` OUTRANKS `allowed_changes`
-----------------------------------------
The two lists can be made to overlap - an over-broad allowance for `start_column`
plus a `line_change` in `forbidden` is a contradiction a reviewer can write by
accident. It resolves toward the stricter reading: a kind named in `forbidden` is
a violation even when an allowance would have matched it. An expectation that
resolved the other way would let a broad allowance silently repeal an explicit
prohibition, which is the wrong direction for a gate to fail in.

FABRICATION IS NEVER ALLOWABLE
------------------------------
`fabricated_column_uniform` and `fabricated_column_collision` are not in the
allowable vocabulary at all, so no expectation can permit them. An allowance for
`start_column` says "a real coordinate appeared". A single constant repeated
across the corpus, or one column shared by two findings that a column exists to
tell apart, is not that claim - it is the same missing information with a number
printed on top, and a file that could sign it off would defeat the check whose
entire job is to notice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

#: The contract this module implements.
CONTRACT = "corpus-delta/v1"

CONTRACT_FILE = Path(__file__).resolve().parent.parent / "contracts" / "corpus-delta-v1.json"

#: Aggregates an expectation can pin as unchanged. Each maps to one comparison in
#: `corpusdiff.diff`; a key not listed here is a typo, and a typo that read as
#: "unpinned" would silently drop a gate the author believed they had set.
UNCHANGED_KEYS = ("pattern_population", "finding_count", "start_line", "start_column")

#: Every change kind the differ can report. This IS the `forbidden` vocabulary.
CHANGE_KINDS = (
    "new_pattern",                    # a pattern present only in the candidate
    "removed_pattern",                # a pattern present only in the baseline
    "path_change",                    # the same rule+message moved file
    "line_change",                    # the same pattern moved line
    "multiplicity_change",            # the same pattern, a different occurrence count
    "start_column_change",            # an occurrence's column moved (see TRANSITIONS)
    "pattern_attribute_change",       # one pattern_id, two different attribute sets
    "ambiguity_increase",             # more anchors indistinguishable than before
    "locationless_increase",          # more findings without a line than before
    "occurrence_coverage_decrease",   # fewer records earned an occurrence_id
    "suppression_census_change",      # the suppressed population moved
    "advisory_census_change",         # the analysis-skipped population moved
    "fabricated_column_uniform",      # every column a producer emits is one constant
    "fabricated_column_collision",    # distinct findings at one site share a column
)

#: Kinds no expectation may permit. See the module docstring.
NEVER_ALLOWABLE = ("fabricated_column_uniform", "fabricated_column_collision")

#: Fields an `allowed_changes` entry may name.
ALLOWABLE_FIELDS = ("start_column",)

#: The transitions an allowance may name, spelled out rather than expressed as a
#: predicate: a reviewer has to be able to read the permission being granted.
TRANSITIONS = (
    "null-to-positive-integer",
    "positive-integer-to-null",
    "positive-integer-to-positive-integer",
)

#: Keys a `corpus-delta/v1` document may carry. Anything else fails the load - an
#: expectation is small enough that a stray key is a mistake, not an extension.
DOCUMENT_KEYS = ("schema", "unchanged", "allowed_changes", "forbidden", "_doc")

#: Keys an `allowed_changes` entry may carry.
ALLOWANCE_KEYS = ("field", "producer", "transition", "_doc")

#: The blanket allowlist, rejected by name.
BANNED_KEY = "allow_any_difference"


class DeltaError(ValueError):
    """The expectation file is unusable. Raised instead of gating on a guess."""


class Expectation:
    """A loaded `corpus-delta/v1` document, with the questions the differ asks.

    Deliberately not a dataclass of raw dicts: every lookup the differ needs goes
    through a named method here, so the resolution rule (`forbidden` outranks
    `allowed_changes`) lives in ONE place and cannot be re-implemented slightly
    differently at a second call site.
    """

    def __init__(self, unchanged: Mapping[str, bool],
                 allowed: list[dict[str, str]], forbidden: list[str]) -> None:
        self._unchanged = dict(unchanged)
        self._allowed = [dict(a) for a in allowed]
        self._forbidden = list(forbidden)

    @property
    def strict(self) -> bool:
        """True for the default expectation - nothing may change at all."""
        return not self._allowed and not self._unchanged and not self._forbidden

    def pins(self, key: str) -> bool:
        """Whether the expectation asserts `key` unchanged."""
        return bool(self._unchanged.get(key))

    def forbids(self, kind: str) -> bool:
        return kind in self._forbidden

    def permits(self, kind: str, producer: str | None = None,
                transition: str | None = None) -> bool:
        """Whether an observed change is signed off.

        `forbidden` is checked FIRST and wins. A kind that is never allowable is
        refused here too, so the rule holds even if a future loader grew a hole.
        """
        if kind in NEVER_ALLOWABLE or self.forbids(kind):
            return False
        if kind != "start_column_change":
            # Only column movement is expressible as an allowance today. Every
            # other kind is either forbidden, pinned, or reported - there is no
            # "generally fine" tier, on purpose.
            return False
        return any(a["field"] == "start_column"
                   and a["producer"] == producer
                   and a["transition"] == transition
                   for a in self._allowed)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONTRACT, "unchanged": dict(sorted(self._unchanged.items())),
                "allowed_changes": self._allowed, "forbidden": list(self._forbidden)}


#: The expectation used when no file is given: nothing may change. Silence means
#: "no intentional delta was declared", and the strict reading is the only one
#: that cannot be reached by forgetting to write the file.
STRICT = Expectation({}, [], [])


def parse(doc: Any) -> Expectation:
    """Validate a `corpus-delta/v1` document and return the expectation.

    Every rejection names the offending value. An expectation is read by CI on a
    branch nobody is watching, so "invalid expectation" without the reason is a
    message that costs an hour.
    """
    if not isinstance(doc, dict):
        raise DeltaError(f"a {CONTRACT} document must be a JSON object")
    if BANNED_KEY in doc:
        raise DeltaError(
            f"{BANNED_KEY!r} is not part of {CONTRACT} and never will be. A gate "
            f"that accepts any difference is not a test - it is written permission "
            f"for the program to surprise you. Name the specific field, producer "
            f"and transition the change is allowed to make, or delete the job so "
            f"its absence is visible.")
    unknown = sorted(k for k in doc if k not in DOCUMENT_KEYS)
    if unknown:
        raise DeltaError(f"unknown {CONTRACT} key(s) {unknown} - allowed: "
                         f"{list(DOCUMENT_KEYS)}")
    if doc.get("schema") != CONTRACT:
        raise DeltaError(f"'schema' must be {CONTRACT!r}, got {doc.get('schema')!r}")

    raw_unchanged = doc.get("unchanged", {})
    if not isinstance(raw_unchanged, dict):
        raise DeltaError("'unchanged' must be an object of flags")
    unchanged: dict[str, bool] = {}
    for key, val in raw_unchanged.items():
        if key not in UNCHANGED_KEYS:
            raise DeltaError(f"unknown 'unchanged' key {key!r} - allowed: "
                             f"{list(UNCHANGED_KEYS)}")
        if not isinstance(val, bool):
            raise DeltaError(f"'unchanged.{key}' must be true or false, got {val!r}")
        unchanged[key] = val

    raw_allowed = doc.get("allowed_changes", [])
    if not isinstance(raw_allowed, list):
        raise DeltaError("'allowed_changes' must be an array of objects")
    allowed: list[dict[str, str]] = []
    for i, entry in enumerate(raw_allowed):
        if not isinstance(entry, dict):
            raise DeltaError(f"allowed_changes[{i}] must be an object")
        bad = sorted(k for k in entry if k not in ALLOWANCE_KEYS)
        if bad:
            raise DeltaError(f"allowed_changes[{i}]: unknown key(s) {bad} - allowed: "
                             f"{list(ALLOWANCE_KEYS)}")
        for key in ("field", "producer", "transition"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise DeltaError(
                    f"allowed_changes[{i}].{key} must be a non-empty string, got "
                    f"{entry.get(key)!r}")
        if entry["field"] not in ALLOWABLE_FIELDS:
            raise DeltaError(
                f"allowed_changes[{i}].field {entry['field']!r} cannot be allowed - "
                f"allowable fields: {list(ALLOWABLE_FIELDS)}")
        if entry["transition"] not in TRANSITIONS:
            raise DeltaError(
                f"allowed_changes[{i}].transition {entry['transition']!r} is not a "
                f"{CONTRACT} transition - allowed: {list(TRANSITIONS)}")
        if entry["producer"] == "*":
            # A wildcard producer is the blanket allowlist wearing a different hat:
            # it signs off a change for tools nobody looked at, including ones added
            # after the expectation was written.
            raise DeltaError(
                f"allowed_changes[{i}].producer must name ONE producer; '*' would "
                f"sign off the change for producers nobody reviewed, including ones "
                f"added later")
        allowed.append({k: entry[k] for k in ("field", "producer", "transition")})

    raw_forbidden = doc.get("forbidden", [])
    if not isinstance(raw_forbidden, list):
        raise DeltaError("'forbidden' must be an array of change kinds")
    forbidden: list[str] = []
    for kind in raw_forbidden:
        if kind not in CHANGE_KINDS:
            raise DeltaError(f"unknown forbidden change kind {kind!r} - allowed: "
                             f"{list(CHANGE_KINDS)}")
        forbidden.append(str(kind))

    # A contradiction the loader can see is worth naming at load time rather than
    # letting `permits` silently resolve it. The resolution is documented and
    # strict, but a reviewer who wrote both meant one of them.
    for entry in allowed:
        if entry["field"] == "start_column" and "start_column_change" in forbidden:
            raise DeltaError(
                "'start_column_change' is in 'forbidden' while 'allowed_changes' "
                "permits a start_column transition - the file contradicts itself; "
                "drop whichever one you did not mean")
    if unchanged.get("start_column") and allowed:
        raise DeltaError(
            "'unchanged.start_column' is true while 'allowed_changes' permits a "
            "start_column transition - the file contradicts itself")

    return Expectation(unchanged, allowed, forbidden)


def load(path: str | Path) -> Expectation:
    """Read and validate an expectation file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise DeltaError(f"cannot read expectation {path}: {e}") from e
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise DeltaError(f"{path} is not valid JSON: {e}") from e
    return parse(doc)


def load_contract(path: str | Path | None = None) -> dict[str, Any]:
    """The contract file - the vocabulary's executable half."""
    return json.loads(Path(path or CONTRACT_FILE).read_text(encoding="utf-8"))


def _selftest() -> int:
    """`PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/delta.py --selftest`"""
    fails: list[str] = []
    doc = load_contract()
    if doc.get("contract") != CONTRACT:
        fails.append(f"contract mismatch: file {doc.get('contract')!r} vs {CONTRACT!r}")
    for name, field in (("change_kinds", CHANGE_KINDS),
                        ("unchanged_keys", UNCHANGED_KEYS),
                        ("transitions", TRANSITIONS),
                        ("never_allowable", NEVER_ALLOWABLE),
                        ("allowable_fields", ALLOWABLE_FIELDS)):
        if doc.get(name) != list(field):
            fails.append(f"{name} drifted: file {doc.get(name)!r} vs module {list(field)}")

    for case in doc.get("accept", []):
        try:
            parse(case["document"])
        except DeltaError as e:
            fails.append(f"{case['name']}: should load, raised {e}")
    for case in doc.get("reject", []):
        try:
            parse(case["document"])
        except DeltaError as e:
            if case["because"] not in str(e):
                fails.append(f"{case['name']}: rejected for the wrong reason: {e}")
        else:
            fails.append(f"{case['name']}: should have been rejected")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"corpusdiff/delta selftest: {'OK' if not fails else 'FAIL'} - "
          f"{len(doc.get('accept', []))} accepted, {len(doc.get('reject', []))} rejected")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
    print("usage: PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/delta.py --selftest")
    raise SystemExit(2)
