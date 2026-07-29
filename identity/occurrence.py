#!/usr/bin/env python3
"""
`finding-occurrence/v1` - identity for one PHYSICAL finding in one producer run
(issue Own.NET#266, slice 1B).

    preimage = b"finding-occurrence/v1\\0"
             + len(f) + b":" + f   for each of, in order:
               producer_run_id, producer_name, pattern_id, path,
               start_line (canonical decimal), start_column ("null" | decimal)
    occurrence_id = sha256(preimage)[:32]

`pattern_id` (`finding-pattern/v1`) answers "which finding is this, as a
pattern" - it deliberately collides across repeats, because one judged verdict
covers a repeated pattern. This answers a different question: "which physical
occurrence, in which run". Two findings of the same pattern at different lines
are two occurrences of one pattern.

WHY THE GATE IS THE INTERESTING PART, NOT THE HASH
--------------------------------------------------
Any recipe can produce a stable-looking hex string. The hard requirement is
refusing to produce one when the inputs do not justify it. An occurrence id is
computed ONLY when every one of these is known:

  * `producer_run_id` - WHICH RUN produced it. This is the field that is most
    often missing and it is the one that cannot be worked around. A digest of
    the SARIF bytes is NOT a run id: two runs can serialize to identical bytes,
    and two serializers of one run can produce different bytes. That value has
    a name already - `input_digest`, a provenance field - and calling it a run
    id would be exactly the neatly-typed lie this whole contract exists to
    prevent.
  * `producer_name` - which tool, so two tools reporting the same site in the
    same audit stay distinct.
  * `pattern_id` - what the finding is.
  * `path` and `start_line` - where it is.
  * an UNAMBIGUOUS anchor within the run - see below.

`producer_version`, `config_digest` and `source_commit` may all be null without
blocking anything. They describe the run; they do not identify the occurrence.

WHEN THERE IS NO COLUMN
-----------------------
`start_column` is nullable and is NEVER synthesized. A missing column is a
*degradation*, not automatically a blocker: a line-only anchor still identifies
an occurrence as long as it is unique within the run. Every such record carries
`physical-anchor-missing:start-column` so the weaker anchor is visible rather
than inferred from an absence.

It becomes a blocker exactly when it stops discriminating: if two records in one
producer run share (`pattern_id`, `path`, `start_line`) and neither has a
column, nothing distinguishes them and BOTH get `occurrence_id: null`. There is
no ordinal tiebreaker, and there will not be one - an ordinal would make
identity depend on the order results happen to be emitted in, which is the same
defect that disqualifies the SARIF `ownAudit/v1` fingerprint as an identity.
Reordering a SARIF file must not re-key the world.

WHY THE FIELDS ARE LENGTH-PREFIXED INSTEAD OF SEPARATOR-JOINED
--------------------------------------------------------------
`finding-pattern/v1` joins its three fields with a raw `\\x1f` and asserts that
the separator cannot occur inside them. That assertion is unchecked, and it is
false in principle: nothing stops a producer from putting a control character in
a message or a path. It is frozen there because every stored overlay is keyed by
those bytes - a documented legacy limitation, not a design.

Here there is no legacy to protect, so the ambiguity is not repeated. With a raw
separator, `("a", "b\\x1fc")` and `("a\\x1fb", "c")` produce the same preimage;
two different occurrences would share an id, and an identity contract that can
confuse two things is not one. Length prefixing removes the question rather than
answering it: every field carries its own byte count, so no arrangement of
contents can be reparsed as a different arrangement of fields. Valid paths stay
valid - the fix is to encode the tuple properly, not to forbid a byte.

The `finding-occurrence/v1\\0` domain prefix keeps this preimage space disjoint
from any other digest computed the same way, so a value from a future contract
cannot be mistaken for one of these.

WHY SHA-256 HERE AND SHA-1 IN `finding-pattern/v1`
--------------------------------------------------
`finding-pattern/v1` is SHA-1 truncated to 16 hex for one reason: every stored
`fp-verdicts.json` overlay is keyed by those exact bytes, and compatibility
outranks a tidier hash. That was a constraint, not an endorsement. Nothing is
keyed by an occurrence id yet, so this one is free to be chosen rather than
inherited.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

#: The contract this module implements.
CONTRACT = "finding-occurrence/v1"

#: Length of the hex digest kept, in characters. Part of the contract.
ID_LENGTH = 32

#: Domain prefix. Keeps this preimage space disjoint from any other contract's.
DOMAIN = b"finding-occurrence/v1\x00"

#: How a null `start_column` renders. Unambiguous against every real column
#: because the field is length-prefixed like the rest - `"null"` is four bytes of
#: field content, not a delimiter or a sentinel the parser has to guess at.
NULL_COLUMN = "null"

CONTRACT_FILE = Path(__file__).resolve().parent.parent / "contracts" / "finding-occurrence-v1.json"

# ---- limitation tokens -------------------------------------------------------
# Machine-readable, `kind:detail`. They travel in the record's
# `identity_limitations`, so a consumer can tell WHY an id is absent instead of
# guessing from a null.

#: No run identity: the normalizer was given no provenance manifest entry for
#: this producer, or the entry carries no `producer_run_id`.
LIMIT_NO_RUN_ID = "occurrence-id-unavailable:producer-run-id"

#: Two or more records in one producer run share an anchor; neither can be told
#: from the other, and an ordinal would be a fabricated distinction.
LIMIT_AMBIGUOUS_ANCHOR = "occurrence-id-unavailable:ambiguous-physical-anchor"

#: The result carried no usable `startLine` (SARIF lines are 1-based, so 0 means
#: "the producer did not say"), leaving nothing to anchor to.
LIMIT_NO_START_LINE = "occurrence-id-unavailable:start-line"

#: The producer emitted no name for the file. Nothing to anchor to.
LIMIT_NO_PATH = "occurrence-id-unavailable:path"

#: Degradation, not a blocker: the anchor is line-only.
LIMIT_NO_START_COLUMN = "physical-anchor-missing:start-column"


def anchor(path: str, start_line: int | None, start_column: int | None) -> dict[str, Any]:
    """The canonical physical anchor.

    `start_column` is `None` when the producer did not report one, and stays
    `None`. It is never 0, never 1, and never a column recovered by re-reading
    the source line - Own.NET's `Diagnostic._caret_col` does exactly that for
    its human-readable caret, by pulling a name out of the message text and
    searching the source line for it, falling back to the indentation. That is
    a renderer heuristic; promoting it to identity would fabricate a coordinate
    the analysis never computed.
    """
    line = start_line if isinstance(start_line, int) and start_line >= 1 else None
    col = start_column if isinstance(start_column, int) and start_column >= 1 else None
    return {"path": path, "start_line": line, "start_column": col}


def anchor_key(producer_run_id: str | None, producer_name: str | None,
               pattern_id: str, physical: Mapping[str, Any]) -> tuple:
    """The tuple whose uniqueness WITHIN a producer run decides ambiguity.

    Exposed rather than inlined because the ambiguity rule and the id must be
    computed from the same fields - if they ever diverge, the normalizer could
    mint an id for an anchor it had just declared indistinct.
    """
    return (producer_run_id, producer_name, pattern_id,
            physical.get("path"), physical.get("start_line"), physical.get("start_column"))


def _framed(value: str) -> bytes:
    """One field, length-prefixed: `<byte length in decimal>:<utf-8 bytes>`.

    The length is of the ENCODED bytes, not of the characters, so a multi-byte
    path frames the same way whatever it contains.
    """
    raw = value.encode("utf-8")
    return b"%d:%s" % (len(raw), raw)


def preimage(producer_run_id: str, producer_name: str, pattern_id: str,
             path: str, start_line: int, start_column: int | None) -> bytes:
    """The exact bytes hashed. Exposed so a test can pin the framing itself, not
    only the digest it happens to produce."""
    col = NULL_COLUMN if start_column is None else str(start_column)
    return DOMAIN + b"".join(_framed(v) for v in (
        producer_run_id, producer_name, pattern_id, path, str(start_line), col))


def occurrence_id(producer_run_id: str, producer_name: str, pattern_id: str,
                  path: str, start_line: int, start_column: int | None) -> str:
    """The raw recipe. Callers should prefer `resolve`, which applies the gate.

    This function does NOT check whether an id is justified; it only computes
    one. It is separate so the contract vectors can pin the bytes independently
    of the policy that decides when to reach for them.
    """
    return hashlib.sha256(preimage(producer_run_id, producer_name, pattern_id,
                                   path, start_line, start_column)).hexdigest()[:ID_LENGTH]


def resolve(pattern_id: str, physical: Mapping[str, Any],
            producer_run_id: str | None, producer_name: str | None,
            ambiguous: bool = False) -> tuple[str | None, list[str]]:
    """`(occurrence_id | None, identity_limitations)` - the gate.

    Returns every applicable limitation, not just the first: a record with no
    run id AND no column has two different things wrong with it, and reporting
    one would understate the situation. The tokens are sorted so the field is
    stable regardless of the order the checks happen to run in.
    """
    limits: list[str] = []
    path = physical.get("path") or ""
    line = physical.get("start_line")
    col = physical.get("start_column")

    if col is None:
        limits.append(LIMIT_NO_START_COLUMN)
    if not producer_run_id or not producer_name:
        limits.append(LIMIT_NO_RUN_ID)
    if not path:
        limits.append(LIMIT_NO_PATH)
    if not isinstance(line, int) or line < 1:
        limits.append(LIMIT_NO_START_LINE)
    if ambiguous:
        limits.append(LIMIT_AMBIGUOUS_ANCHOR)

    blocked = [x for x in limits if x.startswith("occurrence-id-unavailable:")]
    if blocked:
        return None, sorted(limits)
    return occurrence_id(producer_run_id, producer_name, pattern_id, path, line, col), sorted(limits)


def load_vectors(path: str | Path | None = None) -> dict[str, Any]:
    """The canonical vector file - the contract's executable half."""
    return json.loads(Path(path or CONTRACT_FILE).read_text(encoding="utf-8"))


def _selftest() -> int:
    """`PYTHONUTF8=1 PYTHONPATH=. python3 identity/occurrence.py --selftest`"""
    fails: list[str] = []
    doc = load_vectors()

    if doc.get("contract") != CONTRACT:
        fails.append(f"contract mismatch: file {doc.get('contract')!r}, module {CONTRACT!r}")
    if doc.get("id_length") != ID_LENGTH:
        fails.append(f"id_length mismatch: file {doc.get('id_length')!r} vs module {ID_LENGTH}")

    for vec in doc.get("vectors", []):
        got = occurrence_id(vec["producer_run_id"], vec["producer_name"], vec["pattern_id"],
                            vec["path"], vec["start_line"], vec["start_column"])
        if got != vec["occurrence_id"]:
            fails.append(f"{vec['name']}: got {got}, want {vec['occurrence_id']}")
        if len(got) != ID_LENGTH or any(c not in "0123456789abcdef" for c in got):
            fails.append(f"{vec['name']}: {got!r} is not {ID_LENGTH} lower-case hex chars")

    for case in doc.get("gate", []):
        oid, limits = resolve(case["pattern_id"], case["physical_anchor"],
                              case.get("producer_run_id"), case.get("producer_name"),
                              case.get("ambiguous", False))
        want_id = case.get("occurrence_id")
        if (oid is None) != (want_id is None):
            fails.append(f"{case['name']}: occurrence_id presence wrong (got {oid!r}, want {want_id!r})")
        elif want_id is not None and oid != want_id:
            fails.append(f"{case['name']}: got {oid}, want {want_id}")
        if limits != case["identity_limitations"]:
            fails.append(f"{case['name']}: limitations {limits} != {case['identity_limitations']}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"identity/occurrence selftest: {'OK' if not fails else 'FAIL'} "
          f"({len(doc.get('vectors', []))} recipe vectors, {len(doc.get('gate', []))} gate cases)")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
    print("usage: PYTHONUTF8=1 PYTHONPATH=. python3 identity/occurrence.py --selftest")
    raise SystemExit(2)
