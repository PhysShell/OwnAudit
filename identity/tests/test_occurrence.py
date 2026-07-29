"""`finding-occurrence/v1` contract tests. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 identity/tests/test_occurrence.py

Two things are pinned here, and the second is the one that matters.

The RECIPE: the canonical vectors reproduce exactly, an independent
transcription of the recipe agrees with them, and the fields that must
discriminate actually do (run, producer, pattern, path, line, column).

The GATE: when an id is refused, and why. Any recipe can emit a stable-looking
hex string; the hard part is declining to. A missing column is a degradation and
still yields an id while the anchor stays unique; two records sharing an anchor
yield none, with no ordinal tiebreaker; an unknown `producer_run_id` yields none
regardless of how complete everything else is.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from identity.occurrence import (                                                # noqa: E402
    CONTRACT, DOMAIN, ID_LENGTH, NULL_COLUMN, LIMIT_AMBIGUOUS_ANCHOR, LIMIT_NO_RUN_ID,
    LIMIT_NO_START_COLUMN, LIMIT_NO_START_LINE, anchor, anchor_key, load_vectors,
    occurrence_id, preimage, resolve,
)

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
    check(doc["domain_prefix"] == DOMAIN.decode("utf-8"), "the domain prefix drifted")
    check(doc["null_column"] == NULL_COLUMN, "the null-column rendering drifted")

    # 1. Every canonical vector reproduces, exactly.
    for v in vectors:
        got = occurrence_id(v["producer_run_id"], v["producer_name"], v["pattern_id"],
                            v["path"], v["start_line"], v["start_column"])
        check(got == v["occurrence_id"],
              f"{v['name']}: got {got}, contract says {v['occurrence_id']}")
        check(len(got) == ID_LENGTH and all(c in "0123456789abcdef" for c in got),
              f"{v['name']}: {got!r} is not {ID_LENGTH} lower-case hex characters")

    # 2. An independent transcription agrees. Written out here on purpose: vectors
    #    regenerated from the implementation they check agree with themselves and
    #    with nothing else. This is the outside opinion.
    def framed(value: str) -> bytes:
        raw = value.encode("utf-8")
        return str(len(raw)).encode("ascii") + b":" + raw

    for v in vectors:
        col = "null" if v["start_column"] is None else str(v["start_column"])
        ref = hashlib.sha256(
            b"finding-occurrence/v1" + bytes([0]) + b"".join(framed(x) for x in (
                v["producer_run_id"], v["producer_name"], v["pattern_id"],
                v["path"], str(v["start_line"]), col))).hexdigest()[:32]
        check(ref == v["occurrence_id"], f"{v['name']}: transcription disagrees ({ref})")

    # 2b. THE FRAMING ITSELF, not just the digest it happens to produce. A raw
    #     separator join makes ("a", "b<US>c") and ("a<US>b", "c") one preimage --
    #     two different occurrences under one id. This is the defect
    #     `finding-pattern/v1` has to live with for overlay compatibility and the
    #     reason it is not repeated here; the contract carries the pair as vectors.
    us = chr(0x1F)
    p1 = preimage("a", "b" + us + "c", "p", "A.cs", 1, None)
    p2 = preimage("a" + us + "b", "c", "p", "A.cs", 1, None)
    check(p1 != p2,
          "a control character shifted between two fields produced the same preimage - "
          "the length framing is gone or broken")
    check(preimage("a", "bc", "p", "A.cs", 1, None).startswith(DOMAIN),
          "the preimage must carry the domain prefix")
    check(b"1:a" in p1 and b"3:b" + us.encode("utf-8") + b"c" in p1,
          f"fields are not length-prefixed as <bytes>:<utf-8>: {p1!r}")
    # a multi-byte field frames by BYTE length, not character count
    check(b"4:" + "\u0447".encode("utf-8") * 2 in preimage("a", "b", "p", "\u0447\u0447", 1, None),
          "a multi-byte field must be framed by its encoded byte length")

    # 3. Every field in the recipe must discriminate. If any of these collided, an
    #    occurrence would be confusable with one from another run, another tool,
    #    another pattern or another place.
    for a, b in doc["distinct_occurrences"]:
        check(by_name[a]["occurrence_id"] != by_name[b]["occurrence_id"],
              f"{a} and {b} must NOT share an occurrence_id")

    # 4. A null column is not the same as a column, and "null" as a field value is
    #    unambiguous only because the field is framed.
    check(by_name["line-only"]["occurrence_id"] != by_name["column-one"]["occurrence_id"],
          "a null start_column must not hash like column 1")
    check(preimage("r", "n", "p", "A.cs", 1, None) != preimage("r", "n", "p", "A.cs", 1, 0),
          "the null-column rendering must not collide with any real column")

    # 5. THE GATE, case by case, from the contract file.
    for case in doc["gate"]:
        oid, limits = resolve(case["pattern_id"], case["physical_anchor"],
                              case.get("producer_run_id"), case.get("producer_name"),
                              case.get("ambiguous", False))
        check(oid == case["occurrence_id"],
              f"gate {case['name']}: occurrence_id {oid!r} != {case['occurrence_id']!r}")
        check(limits == case["identity_limitations"],
              f"gate {case['name']}: limitations {limits} != {case['identity_limitations']}")

    # 6. The two rules most likely to be "simplified" later, stated directly.
    a_unique = anchor("A.cs", 10, None)
    oid_u, lim_u = resolve("p", a_unique, "run", "own-check", ambiguous=False)
    check(oid_u is not None and lim_u == [LIMIT_NO_START_COLUMN],
          "a UNIQUE line-only anchor must still yield an id - a missing column is a "
          "degradation, not a blocker")
    oid_a, lim_a = resolve("p", a_unique, "run", "own-check", ambiguous=True)
    check(oid_a is None and LIMIT_AMBIGUOUS_ANCHOR in lim_a,
          "an AMBIGUOUS anchor must yield no id, and no ordinal tiebreaker may appear")
    oid_r, lim_r = resolve("p", anchor("A.cs", 10, 4), None, "own-check")
    check(oid_r is None and lim_r == [LIMIT_NO_RUN_ID],
          "a complete anchor with no run id must still yield no id - the run is what "
          "an occurrence is an occurrence OF")

    # 7. The anchor never invents a coordinate.
    check(anchor("A.cs", 0, None)["start_line"] is None, "line 0 must read as None, not 0")
    check(anchor("A.cs", 10, 0)["start_column"] is None, "column 0 must read as None")
    check(anchor("A.cs", 10, None)["start_column"] is None,
          "a missing column must stay None - never 1, never the indentation")
    oid_l, lim_l = resolve("p", anchor("A.cs", 0, None), "run", "own-check")
    check(oid_l is None and LIMIT_NO_START_LINE in lim_l, "no start line must block")

    # 8. The ambiguity key and the id must read the SAME fields. If they diverged,
    #    the normalizer could mint an id for an anchor it had just called indistinct.
    k1 = anchor_key("run", "own-check", "p", anchor("A.cs", 10, None))
    k2 = anchor_key("run", "own-check", "p", anchor("A.cs", 10, 4))
    check(k1 != k2, "the ambiguity key must distinguish a null column from a real one")

    # 9. Limitations are sorted, so the field does not depend on check order.
    _, lim = resolve("p", anchor("", 0, None), None, None, ambiguous=True)
    check(lim == sorted(lim), f"identity_limitations must be sorted: {lim}")
    check(len(lim) == len(set(lim)), f"identity_limitations must not repeat: {lim}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"identity/occurrence: {'OK' if not fails else 'FAIL'} - {len(vectors)} recipe "
          f"vectors, {len(doc['gate'])} gate cases, "
          f"{len(doc['distinct_occurrences'])} distinctness pairs")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
