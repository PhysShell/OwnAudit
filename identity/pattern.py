#!/usr/bin/env python3
"""
`finding-pattern/v1` - the ONE implementation of Own's pattern-level finding
identity, and the domain's canonical definition of it (issue Own.NET#266).

    pattern_id = sha1( path + "\\x1f" + rule + "\\x1f" + message )[:16]

This is the recipe `viz/apply_verdicts.finding_id` has always used
(`docs/fp-judge/verdict-contract.md` section 1); it moves here unchanged so that every
producer and consumer computes identity from one place instead of from one
place each. `apply_verdicts` now imports it, and its `finding_id` name survives
as an alias - the bytes are identical, so existing overlays keep matching.

WHY IT IS NOT "IMPROVED" HERE
-----------------------------
SHA-1 is not a security choice in this role; it is a *compatibility* one. Every
`fp-verdicts.json` overlay in existence is keyed by these exact 16 hex
characters, and the overlay's freshness guard only proves the verdicts were
judged against the same findings file - not that the ids can be recomputed
differently. Changing the algorithm, the separator, the truncation, or the
field order silently orphans every stored verdict: the overlay would simply
stop matching, and a clean report would be indistinguishable from a correct
one. Compatibility outranks a tidier hash.

WHAT IS DELIBERATELY *NOT* NORMALIZED
-------------------------------------
`path`, `rule` and `message` are joined **verbatim**, as UTF-8:

  * no case folding - `Src\\App.cs` and `src\\app.cs` are different findings;
  * no path-separator rewriting - a Windows-style and a POSIX-style spelling of
    the same file are different ids, because the producer chose the spelling
    and identity follows the emitted record, not a guess about the filesystem;
  * no digit or whitespace collapsing in `message` - two findings whose
    messages differ only by a number are different patterns.

The `contracts/finding-pattern-v1.json` vectors pin each of those, so a future
"harmless cleanup" fails a test instead of quietly re-keying the world.

NOT TO BE CONFUSED WITH THE SARIF FINGERPRINT
---------------------------------------------
`report/sarif.py` emits `partialFingerprints["ownAudit/v1"]`, which is a
DIFFERENT value computed a DIFFERENT way (rule/path/normalized-message joined
with newlines, full SHA-1, plus a `/ordinal` suffix for repeats). It exists to
keep GitHub code-scanning alerts correlated across commits and it is a legacy
GitHub-correlation key - **it is not `finding-pattern/v1`**. Its ordinal suffix
alone disqualifies it: identity must not depend on presentation order.

Line is never part of identity: it drifts, and it travels as data for locating
a finding, never for keying one. Two physical findings that share
`(path, rule, message)` share a `pattern_id` ON PURPOSE - one judged verdict
covers the repeated pattern. Telling those physical occurrences apart is the
job of `occurrence_id`, a different identity with different rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

#: The contract this module implements. Bump only with a synchronized change to
#: `contracts/finding-pattern-v1.json` and every consumer that pins it.
CONTRACT = "finding-pattern/v1"

#: Length of the hex digest kept, in characters. Part of the contract.
ID_LENGTH = 16

#: Unit separator: unambiguous join, cannot occur in a path/rule/message.
SEP = "\x1f"

CONTRACT_FILE = Path(__file__).resolve().parent.parent / "contracts" / "finding-pattern-v1.json"


def pattern_id(path: str, rule: str, message: str) -> str:
    """The `finding-pattern/v1` id for one finding's verbatim fields.

    Takes the three fields directly rather than a dict, so a caller cannot
    accidentally feed a *differently shaped* record and get a plausible-looking
    id from the wrong keys.
    """
    key = f"{path}{SEP}{rule}{SEP}{message}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:ID_LENGTH]


def pattern_id_of(finding: Mapping[str, Any]) -> str:
    """`pattern_id` for a normalized finding record.

    The record must carry `path`, `rule` and `message`; a missing one is an
    error rather than an empty string, because silently hashing `""` would mint
    a stable-looking id for an incomplete record and merge unrelated findings
    under it.
    """
    missing = [k for k in ("path", "rule", "message") if k not in finding]
    if missing:
        raise KeyError(
            f"{CONTRACT}: cannot compute pattern_id, record is missing {missing}"
        )
    return pattern_id(finding["path"], finding["rule"], finding["message"])


def load_vectors(path: str | Path | None = None) -> dict[str, Any]:
    """The canonical vector file - the contract's executable half."""
    return json.loads(Path(path or CONTRACT_FILE).read_text(encoding="utf-8"))


def _selftest() -> int:
    """Run the canonical vectors.

    `PYTHONUTF8=1 PYTHONPATH=. python3 identity/pattern.py --selftest`
    """
    fails: list[str] = []
    doc = load_vectors()

    if doc.get("contract") != CONTRACT:
        fails.append(f"contract mismatch: file says {doc.get('contract')!r}, module says {CONTRACT!r}")
    if doc.get("id_length") != ID_LENGTH:
        fails.append(f"id_length mismatch: file {doc.get('id_length')!r} vs module {ID_LENGTH}")

    for vec in doc.get("vectors", []):
        got = pattern_id(vec["path"], vec["rule"], vec["message"])
        if got != vec["pattern_id"]:
            fails.append(f"{vec['name']}: got {got}, want {vec['pattern_id']}")
        if len(got) != ID_LENGTH or any(c not in "0123456789abcdef" for c in got):
            fails.append(f"{vec['name']}: {got!r} is not {ID_LENGTH} lower-case hex chars")

    # The grouping vectors state, as data, which pairs must (not) collide.
    by_name = {v["name"]: v for v in doc.get("vectors", [])}
    for a, b in doc.get("same_pattern", []):
        if pattern_id_of(by_name[a]) != pattern_id_of(by_name[b]):
            fails.append(f"{a} and {b} must share a pattern_id")
    for a, b in doc.get("distinct_patterns", []):
        if pattern_id_of(by_name[a]) == pattern_id_of(by_name[b]):
            fails.append(f"{a} and {b} must NOT share a pattern_id")

    try:
        pattern_id_of({"path": "a", "rule": "b"})
    except KeyError:
        pass
    else:
        fails.append("a record missing `message` must raise, not hash an empty field")

    for f in fails:
        print(f"FAIL: {f}")
    n = len(doc.get("vectors", []))
    print(f"identity/pattern selftest: {'OK' if not fails else 'FAIL'} "
          f"({n} vectors, {len(doc.get('same_pattern', []))} grouping pairs, "
          f"{len(doc.get('distinct_patterns', []))} distinctness pairs)")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if len(sys.argv) == 4:
        print(pattern_id(sys.argv[1], sys.argv[2], sys.argv[3]))
        raise SystemExit(0)
    print(__doc__)
    print("usage: PYTHONUTF8=1 PYTHONPATH=. python3 identity/pattern.py --selftest")
    print("       PYTHONUTF8=1 PYTHONPATH=. python3 identity/pattern.py <path> <rule> <message>")
    raise SystemExit(2)
