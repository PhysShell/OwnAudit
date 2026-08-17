"""Preregistration integrity for `finding-lineage/v1`. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 identity/tests/test_lineage_contract.py

WHAT THIS IS NOT
----------------
It is not a lineage test. There is no mapper (Own.NET#266 slice 2 is frozen at
step 0), so nothing here maps anything. Asserting otherwise would be theatre.

WHAT IT IS
----------
The preregistration, made falsifiable. The ten adversarial cases in
`identity/fixtures/lineage/` were fixed BEFORE any algorithm existed, precisely
so the algorithm could not later select the cases that flatter it. That only
means something if the matrix cannot quietly shrink: a case deleted because it
turned out inconvenient, an expectation softened from `unresolved` to
`continued`, a vocabulary word invented to describe what the code happens to do.

So this suite holds three things:

  1. the matrix is COMPLETE - exactly the preregistered case list, no more, no
     fewer, and named the same;
  2. every expectation uses only vocabulary the frozen contract defines, so an
     outcome cannot be invented to fit an implementation;
  3. every case is well-formed - it has both revisions, and each expectation
     carries what its own outcome requires (a reason for the refusing outcomes,
     a successor for the continuing ones).

When the mapper lands, it gets a second suite that RUNS these fixtures. This one
keeps standing, because its job is different: it guards the questions, not the
answers.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

CONTRACT = os.path.join(ROOT, "contracts", "finding-lineage-v1.json")
FIXDIR = os.path.join(ROOT, "identity", "fixtures", "lineage")
DOC = os.path.join(ROOT, "docs", "finding-lineage.md")

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def main() -> int:
    with open(CONTRACT, encoding="utf-8") as fh:
        contract = json.load(fh)

    outcomes = set(contract["outcomes"])
    evidence_kinds = set(contract["evidence_kinds"])
    limitations = set(contract["limitations"].values())
    preregistered = list(contract["preregistered_cases"])

    # ---- 1. The contract itself is the shape the doc describes. ---------------
    check(contract["contract"] == "finding-lineage/v1",
          f"contract name is {contract.get('contract')!r}")
    check(contract["status"] == "frozen-unimplemented",
          "the contract must declare itself unimplemented until a mapper exists")
    check(outcomes == {"continued", "branched", "merged", "unresolved", "ended", "new"},
          f"the six outcomes changed: {sorted(outcomes)}")

    # The load-bearing rule, asserted rather than only written down: 'unresolved'
    # is what absent evidence yields. If this ever reads 'new', every
    # "introduced this revision" metric silently starts measuring the mapper.
    check(contract["outcomes"]["unresolved"]["lineage_id"] == "null",
          "unresolved must not mint a lineage_id")
    check("reason" == contract["outcomes"]["unresolved"].get("requires"),
          "unresolved must require a reason")
    for refusing in ("unresolved", "ended", "new"):
        check(contract["outcomes"][refusing]["lineage_id"] == "null",
              f"{refusing} must not mint a lineage_id")

    # No evidence kind may carry a `continued` alone. `same_pattern_id` above all:
    # pattern_id collides on purpose, so alone it is the collision, not evidence.
    for kind, spec in contract["evidence_kinds"].items():
        check(spec["sufficient_alone"] is False,
              f"evidence kind {kind!r} claims to be sufficient alone")
        check(bool(spec.get("why")),
              f"evidence kind {kind!r} must say why it is insufficient alone")

    check(set(contract["mapping_provenance_required"]) >=
          {"from_run", "to_run", "from_revision", "to_revision"},
          "mapping provenance must bind BOTH runs and BOTH revisions")

    # ---- 2. The matrix is complete and matches the preregistered list. --------
    on_disk = sorted(f[:-5] for f in os.listdir(FIXDIR) if f.endswith(".json"))
    check(on_disk == sorted(preregistered),
          "the fixture matrix drifted from the preregistered list.\n"
          f"  on disk:       {on_disk}\n"
          f"  preregistered: {sorted(preregistered)}\n"
          "  A case may be ADDED with its contract entry. A case may not be "
          "removed or renamed to make an implementation look better.")
    check(len(preregistered) == 10,
          f"preregistration was 10 cases, contract now lists {len(preregistered)}")

    # ---- 3. Every case is well-formed and speaks only the frozen vocabulary. --
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

        for i, exp in enumerate(case.get("expect", [])):
            where = f"{name}[{i}]"
            outcome = exp.get("outcome")
            check(outcome in outcomes,
                  f"{where}: outcome {outcome!r} is not in the frozen vocabulary")
            seen_outcomes.add(outcome)

            if outcome in ("unresolved", "ended", "new"):
                check(exp.get("reason") in limitations,
                      f"{where}: {outcome} needs a reason from the contract, got {exp.get('reason')!r}")
                # `unresolved` and `ended` are statements about a PREDECESSOR whose
                # successor was not established, so naming one would contradict the
                # outcome. `new` is the mirror image - it is about an occurrence in
                # revision B with no predecessor, so it names that occurrence and
                # leaves `frm` null. Collapsing the three would have made `new`
                # unable to say what it is about.
                if outcome in ("unresolved", "ended"):
                    check(not exp.get("to"),
                          f"{where}: {outcome} must not name a successor")
                    check(exp.get("frm"), f"{where}: {outcome} must name the predecessor it is about")
                else:
                    check(bool(exp.get("to")), f"{where}: `new` must name the occurrence it is about")
            else:
                check(bool(exp.get("to")),
                      f"{where}: {outcome} must name at least one successor")
                for kind in exp.get("evidence_at_least", []):
                    check(kind in evidence_kinds,
                          f"{where}: evidence kind {kind!r} is not in the frozen vocabulary")

            if outcome == "branched":
                check(len(exp.get("to", [])) >= 2,
                      f"{where}: branched with fewer than two successors is a continued")
            if outcome == "new":
                check(exp.get("frm") is None, f"{where}: `new` must have no predecessor")

        for forbidden in case.get("forbid", []):
            check(isinstance(forbidden, str) and forbidden,
                  f"{name}: empty entry in `forbid`")

    # The adversarial core has to be represented, or the matrix is only happy
    # paths wearing the word "adversarial".
    for required in ("unresolved", "branched", "ended", "new", "continued"):
        check(required in seen_outcomes,
              f"no preregistered case expects {required!r} - the matrix is not adversarial")

    # ---- 4. The doc and the contract agree on the case list. -----------------
    with open(DOC, encoding="utf-8") as fh:
        doc = fh.read()
    check("finding-lineage/v1" in doc, "the doc must name the contract it freezes")
    check("implementation not started" in doc,
          "the doc must keep saying no mapper exists, until one does")

    for f in fails:
        print(f"FAIL: {f}")
    if fails:
        print(f"identity/lineage-contract: FAIL - {len(fails)} check(s) failed")
        return 1
    print(f"identity/lineage-contract: OK - {len(preregistered)} preregistered cases, "
          f"{len(outcomes)} outcomes, {len(evidence_kinds)} evidence kinds "
          f"(contract frozen, mapper not implemented)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
