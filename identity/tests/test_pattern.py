"""`finding-pattern/v1` contract tests. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 identity/tests/test_pattern.py

Proves the identity recipe is frozen: the canonical vectors reproduce exactly,
the deliberate non-normalizations hold (path separator, path case, digits,
whitespace), the intentional pattern collision still collides, a record missing
a field raises instead of hashing an empty one, and `apply_verdicts.finding_id`
still returns the same bytes it always did.

That last one is the compatibility guarantee in executable form: every stored
`fp-verdicts.json` is keyed by those bytes, and an overlay that stops matching
yields an empty report rather than an error - a silent failure, so it gets a
test rather than a comment. -O-safe (explicit raises, no bare assert).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from identity.pattern import (                                                    # noqa: E402
    CONTRACT, ID_LENGTH, SEP, CONTRACT_FILE, load_vectors, pattern_id, pattern_id_of,
)
from viz.apply_verdicts import finding_id                                         # noqa: E402

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def main() -> int:
    doc = load_vectors()
    vectors = doc["vectors"]
    by_name = {v["name"]: v for v in vectors}

    check(doc["contract"] == CONTRACT, f"contract name drifted: {doc['contract']!r}")
    check(doc["id_length"] == ID_LENGTH, f"id_length drifted: {doc['id_length']!r}")
    check(doc["separator"] == SEP, "separator drifted from the unit separator")

    # 1. Every canonical vector reproduces, exactly.
    for v in vectors:
        got = pattern_id(v["path"], v["rule"], v["message"])
        check(got == v["pattern_id"],
              f"{v['name']}: got {got}, contract says {v['pattern_id']}")
        check(len(got) == ID_LENGTH and all(c in "0123456789abcdef" for c in got),
              f"{v['name']}: {got!r} is not {ID_LENGTH} lower-case hex characters")

    # 2. An independent transcription of the recipe agrees. Written out here on
    #    purpose: if pattern.py and the vectors were ever regenerated together
    #    from a changed implementation, both would agree with each other and
    #    with nothing else. This line is the outside opinion.
    for v in vectors:
        ref = hashlib.sha1(
            (v["path"] + "\x1f" + v["rule"] + "\x1f" + v["message"]).encode("utf-8")
        ).hexdigest()[:16]
        check(ref == v["pattern_id"], f"{v['name']}: recipe transcription disagrees ({ref})")

    # 3. The deliberate non-normalizations.
    for a, b in doc["distinct_patterns"]:
        check(pattern_id_of(by_name[a]) != pattern_id_of(by_name[b]),
              f"{a} and {b} must NOT share a pattern_id - a normalization crept in")
    for a, b in doc["same_pattern"]:
        check(pattern_id_of(by_name[a]) == pattern_id_of(by_name[b]),
              f"{a} and {b} must share a pattern_id - the repeated-pattern collision is intentional")

    # 4. A missing field raises; an EMPTY field does not.
    for missing in ("path", "rule", "message"):
        rec = {"path": "p", "rule": "r", "message": "m"}
        del rec[missing]
        try:
            pattern_id_of(rec)
        except KeyError:
            pass
        else:
            fails.append(f"a record missing {missing!r} must raise, not hash an empty field")
    check(pattern_id_of({"path": "src/Empty.cs", "rule": "OWN050", "message": ""})
          == by_name["empty-message"]["pattern_id"],
          "an empty message must hash as empty, not raise")

    # 5. Extra keys on the record change nothing - identity reads three fields.
    check(pattern_id_of({**by_name["posix-style-path"], "line": 42, "tool": "own-check"})
          == by_name["posix-style-path"]["pattern_id"],
          "line/tool leaked into the identity")

    # 6. THE compatibility guarantee: the overlay-facing alias is byte-identical.
    for v in vectors:
        check(finding_id(v) == v["pattern_id"],
              f"{v['name']}: apply_verdicts.finding_id drifted from the contract")

    # 7. The SARIF fingerprint is a DIFFERENT value and must not be mistaken for
    #    this one - it normalizes the message and appends an ordinal.
    from report.sarif import _fingerprint                                         # noqa: E402
    v = by_name["message-with-digits"]
    check(_fingerprint(v) != v["pattern_id"],
          "the SARIF ownAudit/v1 fingerprint must not equal pattern_id - it is a legacy "
          "GitHub-correlation key with different rules")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"identity/pattern: {'OK' if not fails else 'FAIL'} - {len(vectors)} vectors, "
          f"{len(doc['distinct_patterns'])} distinctness pairs, "
          f"{len(doc['same_pattern'])} collision pairs, alias byte-identical")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
