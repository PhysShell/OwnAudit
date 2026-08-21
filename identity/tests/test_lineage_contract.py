"""Preregistration integrity for `finding-lineage/v1`. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 identity/tests/test_lineage_contract.py

WHAT THIS IS NOT
----------------
It is not a lineage test. There is no mapper (Own.NET#266 slice 2 is frozen at
step 0), so nothing here maps anything. Asserting otherwise would be theatre.

WHAT IT IS
----------
The preregistration, made falsifiable. The adversarial cases in
`identity/fixtures/lineage/` were fixed BEFORE any algorithm existed, precisely
so the algorithm could not later select the cases that flatter it. That only
means something if the matrix cannot quietly shrink: a case deleted because it
turned out inconvenient, an expectation softened from `unresolved` to
`continued`, a vocabulary word invented to describe what the code happens to do.

So this suite holds five things:

  1. the matrix is COMPLETE - exactly the preregistered case list, no more, no
     fewer, and named the same - and every one of the six frozen outcomes is
     exercised by it, so none is frozen in name only;
  2. every expectation uses only vocabulary the frozen contract defines, so an
     outcome cannot be invented to fit an implementation;
  3. `ended` and `new` are EARNED. An identity limitation may not justify them,
     their boundary evidence must be present as DATA in the fixture and must
     actually match the occurrence it is about, and it must not be defeated by
     another record in the same revision;
  4. `unresolved` is symmetric - it anchors on the A side or the B side - and
     every occurrence on both sides is accounted for by some expectation, so an
     unexplained occurrence is a stated refusal rather than a silence;
  5. the lineage-id semantics (inherit / mint / branch / merge) are fixed in the
     contract and respected by the fixtures.

When the mapper lands, it gets a second suite that RUNS these fixtures. This one
keeps standing, because its job is different: it guards the questions, not the
answers.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

CONTRACT = os.path.join(ROOT, "contracts", "finding-lineage-v1.json")
FIXDIR = os.path.join(ROOT, "identity", "fixtures", "lineage")
DOC = os.path.join(ROOT, "docs", "finding-lineage.md")

OUTCOMES = ("continued", "branched", "merged", "unresolved", "ended", "new")
REFUSING = ("unresolved", "ended", "new")
EARNED_ABSENCE = ("ended", "new")

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def as_list(value) -> list:
    """`frm` is one id for a 1:N outcome and a list for `merged`."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def collect(revision: dict, spec: str) -> list:
    """Read a contract field path such as `revision_b.renames[].from`.

    The contract names where each boundary fact is observable rather than
    hardcoding it here, so a kind cannot be added with no way to check it.
    """
    body = spec.split(".", 1)[1]
    if "[]." not in body:
        return list(revision.get(body, []))
    field, key = body.split("[].")
    out: list = []
    for entry in revision.get(field, []):
        value = entry.get(key)
        if isinstance(value, list):
            out.extend(value)
        elif value is not None:
            out.append(value)
    return out


SIDE_COUNTS = {"0": (0, 0), "1": (1, 1), "N": (2, None)}


def cardinality_shape_failures(where: str, outcome: str, shape, frm, to) -> list:
    """The `<predecessors>:<successors>` shape an outcome declares, enforced FROM
    that declaration.

    Every one of the six shapes was enforced here as a literal - `continued is
    1:1`, `branched is 1:N`, `merged is N:1`, and the ended/new pair as separate
    length checks - spread over three blocks, and `outcomes.*.cardinality` was
    read nowhere in this file. Editing the senior contract to say `continued` is
    `1:N` left every one of them still enforcing `1:1` while citing the contract
    they had stopped agreeing with.

    The junior suite had exactly this defect and it was fixed one commit earlier;
    the senior contract's own suite was the adjacent site nobody asked. That is
    the shape this branch keeps repeating, and this time it was committed
    alongside a message describing it.

    `N` means at least two, which is what these checks already meant - "branched
    with fewer than two successors is a continued". Reading it off the shape
    binds the literal without changing what is enforced. An unparseable side is
    reported rather than skipped: a shape nobody can read is not a shape that
    constrains anything."""
    out = []
    sides = str(shape).split(":")
    if len(sides) != 2 or any(s not in SIDE_COUNTS for s in sides):
        return [f"{where}: outcome {outcome!r} declares cardinality {shape!r}, which "
                f"is not `<predecessors>:<successors>` over {sorted(SIDE_COUNTS)}. "
                "Nothing can be enforced from a shape that cannot be read."]
    for token, label, got in zip(sides, ("predecessor", "successor"), (frm, to)):
        low, high = SIDE_COUNTS[token]
        if len(got) < low or (high is not None and len(got) > high):
            want = f"at least {low}" if high is None else str(low)
            out.append(f"{where}: {outcome} is {shape} in the senior contract, so it "
                       f"names {want} {label}(s), got {len(got)}. A group of one is the "
                       "1:1 outcome under another name, and a group of none is not an "
                       "outcome at all.")
    return out


AMENDMENT_ORDINALS = {"again": 2, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                      "sixth": 6, "seventh": 7, "eighth": 8}


def amendment_ordinal_failures(note) -> list:
    """The revision history counts itself, so the count is checked.

    Two entries both said "third" - one lower-case, one shouting - and the entry
    after them said "FOURTH", because each amendment was written by reading the
    previous one rather than by counting. A revision history whose ordinals
    disagree is the same defect as prose restating a declared number, one level
    up: the number is a fact about the document, and nothing was checking it.

    The pre-merge correction is revision one and is not an amendment, so the
    n-th amendment is revision n + 1."""
    out = []
    seen = []
    for line in note if isinstance(note, list) else []:
        if not isinstance(line, str) or not line.startswith("Amended"):
            continue
        words = [w.strip(",.").lower() for w in line.split()[:4]]
        found = [AMENDMENT_ORDINALS[w] for w in words if w in AMENDMENT_ORDINALS]
        if not found:
            out.append(f"revision_note: {line!r} amends the contract without saying "
                       "which amendment it is")
            continue
        seen.append((line, found[0]))
    for index, (line, ordinal) in enumerate(seen):
        want = index + 2
        if ordinal != want:
            out.append(f"revision_note: amendment {index + 1} calls itself revision "
                       f"{ordinal}, but it is revision {want} - {line!r}")
    return out


def main() -> int:
    with open(CONTRACT, encoding="utf-8") as fh:
        contract = json.load(fh)

    outcomes = set(contract["outcomes"])
    evidence_kinds = set(contract["evidence_kinds"])
    limitations = set(contract["limitations"].values())
    boundary = contract["boundary_evidence_kinds"]
    boundary_values = {spec["value"]: spec for spec in boundary.values()}
    preregistered = list(contract["preregistered_cases"])
    floor = contract["minimum_evidence_kinds_for_continued"]
    parent_field = contract["parent_lineage_field"]

    # ---- 1. The contract itself is the shape the doc describes. ---------------
    check(contract["contract"] == "finding-lineage/v1",
          f"contract name is {contract.get('contract')!r}")
    check(contract["status"] == "frozen-unimplemented",
          "the contract must declare itself unimplemented until a mapper exists")
    check(outcomes == set(OUTCOMES), f"the six outcomes changed: {sorted(outcomes)}")
    for msg in amendment_ordinal_failures(contract.get("revision_note")):
        check(False, msg)

    # The load-bearing rule, asserted rather than only written down: absent
    # evidence yields 'unresolved'. If this ever reads 'new', every "introduced
    # this revision" metric silently starts measuring the mapper.
    check("reason" in contract["outcomes"]["unresolved"]["requires"],
          "unresolved must require a reason")

    # A lineage_id records MEMBERSHIP in a lineage graph, not "an edge was
    # proven" - that tidier invariant made a root node unrepresentable. So a
    # refusal seeds nothing, an ending invents nothing, and an evidenced birth
    # seeds the root a later branch will have to name as its parent.
    seeding = contract.get("root_seeding_rules", {})
    check(set(seeding) == set(OUTCOMES),
          f"root seeding must be stated for every outcome, missing {sorted(set(OUTCOMES) - set(seeding))}")
    check(contract["outcomes"]["unresolved"]["lineage_id"] == "null",
          "unresolved must not mint a lineage_id - a refusal that minted one would be membership")
    check(contract["outcomes"]["ended"]["lineage_id"] == "none-minted",
          "ended must mint nothing; an unlinked predecessor stays a terminal occurrence")
    check(contract["outcomes"]["new"]["lineage_id"] == "minted-root",
          "an evidenced birth must seed a root lineage, or a later branch from it "
          "has no parent lineage to record and an occurrence id gets used instead")
    check(bool(contract.get("lineage_id_existence")),
          "the contract must state when a lineage_id exists")

    # `unresolved` has to be sayable about an occurrence in B, or an unmatched B
    # occurrence has nowhere to go but `new` and the SCHEMA fabricates the birth.
    sides = contract["outcomes"]["unresolved"].get("sides", {})
    check(set(sides) == {"a", "b"},
          f"unresolved must be anchorable on both sides, got {sorted(sides)}")
    check("side" in contract["outcomes"]["unresolved"]["requires"],
          "unresolved must require an explicit side")

    # ---- 2. Two vocabularies, kept apart. -------------------------------------
    # An identity limitation says the mapper could not reach an answer. Boundary
    # evidence says the world has an edge there. Letting one stand in for the
    # other is precisely how "I found nothing" became a death and a birth.
    for outcome in EARNED_ABSENCE:
        check(contract["outcomes"][outcome].get("requires") == "boundary_evidence",
              f"{outcome} must require boundary evidence, not a limitation")
    check(not (limitations & set(boundary_values)),
          "identity limitations and boundary evidence must not share any value")
    for value in limitations:
        check(value.startswith("lineage-id-unavailable:"),
              f"limitation {value!r} lost its prefix")
    for name, spec in boundary.items():
        check(spec["value"] == f"boundary:{name}",
              f"boundary kind {name!r} has value {spec['value']!r}")
        check(spec["proves"] in EARNED_ABSENCE,
              f"boundary kind {name!r} proves {spec['proves']!r}")
        for field in ("observable_from", "match", "why", "defeated_by", "defeated_why"):
            check(bool(spec.get(field)), f"boundary kind {name!r} must state {field!r}")
        # A boundary asserted in prose is not a boundary: absence of a matching
        # occurrence in revision B is what `unresolved` already covers, so it can
        # never be what distinguishes `ended` from it.
        check(spec["observable_from"].startswith("revision_b."),
              f"boundary kind {name!r} must be observable from revision B data")
        check(spec["match"] in ("predecessor.path", "successor.path",
                                "predecessor.enclosing_symbol", "successor.enclosing_symbol"),
              f"boundary kind {name!r} has an unusable match target {spec['match']!r}")

    # No evidence kind may carry a `continued` alone. `same_pattern_id` above all:
    # pattern_id collides on purpose, so alone it is the collision, not evidence.
    check(isinstance(floor, int) and floor >= 2,
          f"the evidence floor must be at least 2 while no kind is sufficient alone, got {floor!r}")
    for kind, spec in contract["evidence_kinds"].items():
        check(spec["sufficient_alone"] is False,
              f"evidence kind {kind!r} claims to be sufficient alone")
        check(bool(spec.get("why")),
              f"evidence kind {kind!r} must say why it is insufficient alone")

    # ---- 3. Graph semantics are the contract's business, not the mapper's. ----
    id_rules = contract.get("lineage_id_rules", {})
    check(set(id_rules) == {"inherit", "mint", "branch", "merge"},
          f"the four lineage-id rules changed: {sorted(id_rules)}")
    check(set(contract.get("parent_lineage_required_for", [])) == {"branched", "merged"},
          "branched and merged are exactly the outcomes that must record parent lineage")

    check(set(contract["mapping_provenance_required"]) >=
          {"from_run", "to_run", "from_revision", "to_revision"},
          "mapping provenance must bind BOTH runs and BOTH revisions")
    # A bare mapper name cannot support "would this mapping still be made?": two
    # runs of one name under different thresholds would look like one mapper.
    check(set(contract["mapping_provenance_required"]) >=
          {"mapper", "mapper_version", "mapper_config_digest", "contract_version"},
          "mapping provenance must pin the mapper's version, config and contract")

    # ---- 4. The matrix is complete and matches the preregistered list. --------
    on_disk = sorted(f[:-5] for f in os.listdir(FIXDIR) if f.endswith(".json"))
    check(on_disk == sorted(preregistered),
          "the fixture matrix drifted from the preregistered list.\n"
          f"  on disk:       {on_disk}\n"
          f"  preregistered: {sorted(preregistered)}\n"
          "  A case may be ADDED with its contract entry. A case may not be "
          "removed or renamed to make an implementation look better.")

    # ---- 5. Every case is well-formed and speaks only the frozen vocabulary. --
    seen_outcomes: set[str] = set()
    for name in sorted(set(on_disk) & set(preregistered)):
        with open(os.path.join(FIXDIR, f"{name}.json"), encoding="utf-8") as fh:
            case = json.load(fh)

        check(case.get("case") == name, f"{name}: case field is {case.get('case')!r}")
        check(case.get("contract") == "finding-lineage/v1", f"{name}: wrong contract")
        for field in ("title", "why", "revision_a", "revision_b", "expect"):
            check(field in case, f"{name}: missing {field!r}")
        # `why` is not decoration: a preregistered case whose reason is not
        # written down cannot be defended later against "this one is awkward".
        check(len(case.get("why", "")) > 40, f"{name}: `why` must state what the case defends")
        check(bool(case.get("expect")), f"{name}: no expectation - nothing is preregistered")

        rev_a = case.get("revision_a", {})
        rev_b = case.get("revision_b", {})
        occ_a = {o["occurrence_id"]: o for o in rev_a.get("occurrences", [])}
        occ_b = {o["occurrence_id"]: o for o in rev_b.get("occurrences", [])}
        established = rev_a.get("established_lineage", {})
        claimed_a: set[str] = set()
        claimed_b: set[str] = set()

        for i, exp in enumerate(case.get("expect", [])):
            where = f"{name}[{i}]"
            outcome = exp.get("outcome")
            check(outcome in outcomes,
                  f"{where}: outcome {outcome!r} is not in the frozen vocabulary")
            seen_outcomes.add(outcome)
            frm = as_list(exp.get("frm"))
            to = as_list(exp.get("to"))
            claimed_a.update(frm)
            claimed_b.update(to)
            for occ in frm:
                check(occ in occ_a, f"{where}: predecessor {occ!r} is not in revision A")
            for occ in to:
                check(occ in occ_b, f"{where}: successor {occ!r} is not in revision B")

            if outcome == "unresolved":
                side = exp.get("side")
                check(side in ("a", "b"), f"{where}: unresolved needs side 'a' or 'b', got {side!r}")
                # The two sides are mirror images and each must say what it is
                # about; an unresolved naming neither end states nothing at all.
                if side == "a":
                    check(len(frm) == 1, f"{where}: unresolved(a) must name one predecessor")
                    check(not to, f"{where}: unresolved(a) must not name a successor")
                elif side == "b":
                    check(len(to) == 1, f"{where}: unresolved(b) must name one occurrence in B")
                    check(not frm, f"{where}: unresolved(b) must not name a predecessor")
                check(exp.get("reason") in limitations,
                      f"{where}: unresolved needs a reason from the contract, got {exp.get('reason')!r}")
                # A first run has no revision A. Saying so while revision A is
                # right there is how the coincidence case originally justified a
                # fabricated birth.
                if exp.get("reason") == contract["limitations"]["no-predecessor-revision"]:
                    check(not occ_a,
                          f"{where}: no-predecessor-revision claimed while revision A has occurrences")

            elif outcome in EARNED_ABSENCE:
                check("reason" not in exp,
                      f"{where}: {outcome} must not carry an identity limitation - "
                      "absence of a match is unresolved, not a boundary")
                kinds = exp.get("boundary_evidence") or []
                check(bool(kinds), f"{where}: {outcome} must be earned by boundary evidence")
                # `ended` is 1:0 and `new` is 0:1 in the senior contract, and
                # both halves of each come off that declaration now.
                for msg in cardinality_shape_failures(
                        where, outcome,
                        contract["outcomes"][outcome].get("cardinality"), frm, to):
                    check(False, msg)
                for kind in kinds:
                    spec = boundary_values.get(kind)
                    check(spec is not None,
                          f"{where}: boundary evidence {kind!r} is not in the frozen vocabulary")
                    if spec is None:
                        continue
                    check(spec["proves"] == outcome,
                          f"{where}: {kind!r} proves {spec['proves']!r}, not {outcome!r}")
                    role, attr = spec["match"].split(".")
                    subject = (occ_a.get(frm[0]) if role == "predecessor" and frm
                               else occ_b.get(to[0]) if role == "successor" and to
                               else None)
                    if subject is None:
                        check(False, f"{where}: {kind!r} has no {role} to match against")
                        continue
                    wanted = subject.get(attr)
                    observed = collect(rev_b, spec["observable_from"])
                    # The fixture must CARRY the fact. A boundary that lives only
                    # in a note is the absence of a match wearing a better word.
                    check(wanted in observed,
                          f"{where}: {kind!r} claims {spec['observable_from']} names "
                          f"{wanted!r}, but it holds {observed!r}")
                    # `defeated_by` is contract data, and this loop reads revision B
                    # with it. An unvalidated path would either explode on a
                    # non-string or, worse, silently read a `revision_a.` defeater
                    # out of revision B and report a defeat that never happened.
                    raw = spec["defeated_by"]
                    if not isinstance(raw, str):
                        check(False, f"{kind!r}: defeated_by must be a string, got {type(raw).__name__}")
                        continue
                    defeaters = [d.strip() for d in raw.split(",")]
                    if not all(defeaters) or not all(d.startswith("revision_b.") for d in defeaters):
                        check(False, f"{kind!r}: every defeated_by path must be a non-empty "
                                     f"`revision_b.` path, got {defeaters!r}")
                        continue
                    for defeater in defeaters:
                        check(wanted not in collect(rev_b, defeater),
                              f"{where}: {kind!r} is defeated - {wanted!r} appears in "
                              f"{defeater}, so the boundary is explained away")

            else:
                check(bool(to), f"{where}: {outcome} must name at least one successor")
                required = exp.get("evidence_at_least", [])
                for kind in required:
                    check(kind in evidence_kinds,
                          f"{where}: evidence kind {kind!r} is not in the frozen vocabulary")
                if outcome == "continued":
                    # The floor is a rule about what may CARRY a continued, so a
                    # preregistered case that names fewer kinds than the floor sits
                    # under the contract it is supposed to pin down - and CI would
                    # accept a mapper that does the same.
                    check(bool(required),
                          f"{where}: continued must name the evidence that carries it")
                    alone_ok = any(contract["evidence_kinds"].get(k, {}).get("sufficient_alone")
                                   for k in required)
                    check(alone_ok or len(required) >= floor,
                          f"{where}: continued names {len(required)} evidence kind(s) "
                          f"{required}, and none is sufficient alone; the frozen floor is "
                          f"{floor}. Name the evidence that really fired, or promote a kind.")
                if outcome == "continued":
                    # The inherit rule: a predecessor that already carries a
                    # lineage passes THAT id on. A re-mint would read as a new
                    # defect appearing where an old one was proven to persist.
                    if frm and frm[0] in established:
                        check(exp.get("lineage_id") == established[frm[0]],
                              f"{where}: predecessor carries {established[frm[0]]!r}; "
                              f"the successor must inherit it, not {exp.get('lineage_id')!r}")
                if outcome in ("continued", "branched", "merged"):
                    for msg in cardinality_shape_failures(
                            where, outcome,
                            contract["outcomes"][outcome].get("cardinality"), frm, to):
                        check(False, msg)
                if outcome in ("branched", "merged"):
                    # A child with no recorded parent is a birth wearing another
                    # word, and a merge that records one parent has quietly
                    # elected it. Either way the graph loses what happened.
                    #
                    # And the parents are LINEAGE ids. An occurrence_id is built
                    # from producer_run_id and cannot span runs by construction,
                    # so one stored in a cross-revision field is a claim made out
                    # of something that provably cannot carry it. The fixture
                    # says `lin-of:<occ>` - the lineage OF that occurrence,
                    # seeded as a root first if it has none - or a literal id it
                    # already declared in `established_lineage`.
                    parents = exp.get("parent_lineage_ids", [])
                    resolved: list[str] = []
                    for ref in parents:
                        check(ref not in occ_a and ref not in occ_b,
                              f"{where}: parent_lineage_ids holds occurrence id {ref!r}. "
                              "Parents are lineages; an occurrence id cannot span runs.")
                        if isinstance(ref, str) and ref.startswith("lin-of:"):
                            resolved.append(ref[len("lin-of:"):])
                        elif ref in established.values():
                            resolved.extend(o for o, lid in established.items() if lid == ref)
                        else:
                            check(False,
                                  f"{where}: parent_lineage_ids entry {ref!r} names no lineage - "
                                  "use `lin-of:<occurrence_id>` or a declared established id")
                    check(sorted(resolved) == sorted(frm),
                          f"{where}: {outcome} must record a parent lineage for every "
                          f"predecessor, got {parents!r} resolving to {sorted(resolved)} for {sorted(frm)}")

            if outcome == "new":
                # The birth seeds a root. A fixture that pinned it to null would
                # re-open the hole this rule closes.
                check("lineage_id" in exp and exp["lineage_id"],
                      f"{where}: `new` seeds a ROOT lineage, so the case must name it. "
                      "Omitting it preregisters nothing about root seeding - and a default "
                      "sentinel that treats absence as 'fine' is how this check first "
                      "passed without ever looking.")

        # Nothing may be dropped in silence. An occurrence the matrix does not
        # mention is indistinguishable from one a mapper forgot to report.
        check(claimed_a == set(occ_a),
              f"{name}: revision A occurrences unaccounted for: {sorted(set(occ_a) - claimed_a)}")
        check(claimed_b == set(occ_b),
              f"{name}: revision B occurrences unaccounted for: {sorted(set(occ_b) - claimed_b)}")

        seen_forbid: set[str] = set()
        for forbidden in case.get("forbid", []):
            check(isinstance(forbidden, str) and forbidden,
                  f"{name}: empty entry in `forbid`")
            check(forbidden not in seen_forbid,
                  f"{name}: `forbid` repeats an entry verbatim: {forbidden[:60]!r}")
            seen_forbid.add(forbidden)
            # `forbid` is prose, but it NAMES fields, and a name nothing answers to
            # is worse than no name: it reads as a real constraint. A bulk rename
            # of `parent_lineage` -> `parent_lineage_ids` produced
            # `parent_lineage_ids_ids` here and shipped, because prose was checked
            # only for being non-empty.
            for hit in re.findall(r"parent_lineage\w*", forbidden):
                check(hit == parent_field,
                      f"{name}: `forbid` names {hit!r}; the contract's field is "
                      f"{parent_field!r} and nothing answers to any other spelling")

    # Every frozen outcome must be exercised, or it is frozen in name only and a
    # mapper may implement it however it likes without failing preregistration.
    for required in OUTCOMES:
        check(required in seen_outcomes,
              f"no preregistered case expects {required!r} - that outcome is frozen in name only")

    # ---- 6. The doc and the contract agree. ----------------------------------
    with open(DOC, encoding="utf-8") as fh:
        doc = fh.read()
    check("finding-lineage/v1" in doc, "the doc must name the contract it freezes")
    check("implementation not started" in doc,
          "the doc must keep saying no mapper exists, until one does")
    for case_name in preregistered:
        check(case_name in doc, f"the doc does not mention preregistered case {case_name!r}")

    for f in fails:
        print(f"FAIL: {f}")
    if fails:
        print(f"identity/lineage-contract: FAIL - {len(fails)} check(s) failed")
        return 1
    print(f"identity/lineage-contract: OK - {len(preregistered)} preregistered cases, "
          f"{len(outcomes)} outcomes (all exercised), {len(evidence_kinds)} evidence kinds, "
          f"{len(boundary)} boundary kinds (contract frozen, mapper not implemented)")
    return 0


def test_lineage_contract() -> None:
    """Pytest entry point.

    Without it `pytest` collects nothing from this file and reports success - a
    green run that checked exactly zero things, which is the failure mode this
    whole suite exists to prevent one level up. The bare-script path below stays
    the primary one, because `pytest` is not guaranteed in the dev shell.
    """
    rc = main()
    if rc != 0:
        raise AssertionError(f"lineage contract integrity failed: {len(fails)} check(s)")


if __name__ == "__main__":
    raise SystemExit(main())
