"""Structural integrity for `finding-lineage-decision/v1`. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 identity/tests/test_lineage_decision.py

WHAT THIS IS NOT
----------------
Not a mapper test, and not an applicability test. There is no mapper, and
whether a real evidence record can produce a given set of rule applications is
what the fixtures are for. This suite never asks whether a signal combination is
physically possible: that is domain reasoning, and a checker doing it would be a
second mapper, hidden and worse dressed than the first.

It is also not a test of its own arbitration function. That distinction matters
enough to state: writing an evaluator, running it over every subset, and
observing that it always returns something proves only that the evaluator is
total. The claim being checked is about the CONTRACT's declared classifications,
so the properties below are read off the contract and the sweep is a cross-check
on a proof, not the proof itself.

THE THREE PROPERTIES, AND WHICH ARE INDEPENDENT
-----------------------------------------------
  1. PAIR COMPLETENESS - every unordered pair of declared rule ids with
     DIFFERENT outcomes is classified exactly once: an explicit dominance edge,
     or an explicit deliberate refusal. Never both, never neither.
  2. DOMINANCE SANITY - edges name existing ids, never self-edge, always span
     different outcomes, never appear in both directions, and the graph is
     acyclic. No transitivity is inferred: A>B and B>C do not create A>C.
  3. TOTALITY - every non-empty subset of declared ids yields exactly one
     result, independent of enumeration order.

1 and 2 are independent axioms, and two probes show neither implies the other.
3 is NOT a third axiom: it is a THEOREM of 1 and 2 plus the absorbing refusal
rule, and the suite says so rather than staging it as one.

    Let S be a subset with more than one outcome and no refusal-classified pair.
    By completeness every different-outcome pair inside S is a dominance edge.
    (a) Survivors cannot span two outcome classes: if a and b both survive with
        different outcomes, {a, b} is a different-outcome pair, so it is an edge
        in one direction or the other, and whichever way it points gives one of
        them an incoming edge from inside S. Contradiction.
    (b) Survivors cannot be empty: dominance restricted to S is acyclic, and a
        finite acyclic digraph has a source.
    Therefore the survivor set is non-empty and single-outcome, so the result
    exists and is unique. Order never enters the argument.

The sweep is kept anyway, because a proof holds for the contract as it is today
and the sweep re-checks it after every future edit - including edits that break
an assumption the proof leans on without anyone noticing which one.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SENIOR = os.path.join(ROOT, "contracts", "finding-lineage-v1.json")
POLICY = os.path.join(ROOT, "contracts", "finding-lineage-decision-v1.json")

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dominance_edges(policy: dict) -> set:
    return {(p["winner"], loser)
            for p in policy["dominance"]["declared_pairs"]
            for loser in p["loses"]}


def refusal_pairs(policy: dict) -> set:
    return {frozenset(c["between"]) for c in policy["deliberately_unresolved_conflicts"]}


def has_cycle(nodes, edges) -> bool:
    seen, stack = set(), set()

    def walk(node) -> bool:
        if node in stack:
            return True
        if node in seen:
            return False
        seen.add(node)
        stack.add(node)
        found = any(walk(m) for (w, m) in edges if w == node)
        stack.discard(node)
        return found

    return any(walk(n) for n in nodes)


def arbitrate(subset, outcomes, edges, refusals):
    """The contract's procedure, read structurally. Returns None for 'no defined
    result', which the theorem says is unreachable - the sweep is what keeps that
    honest after a future edit."""
    s = set(subset)
    if not s:
        return None
    outs = {outcomes[r] for r in s}
    if len(outs) == 1:
        return (outs.pop(), frozenset(s))
    for pair in itertools.combinations(sorted(s), 2):
        if frozenset(pair) in refusals:
            return ("unresolved", frozenset())
    survivors = {r for r in s if not any((w, r) in edges for w in s)}
    souts = {outcomes[r] for r in survivors}
    if len(souts) == 1:
        return (souts.pop(), frozenset(survivors))
    return None


def main() -> int:
    senior = load(SENIOR)
    policy = load(POLICY)

    rules = policy["rules"]
    ids = sorted(rules)
    outcomes = {r: rules[r]["outcome"] for r in ids}
    edges = dominance_edges(policy)
    refusals = refusal_pairs(policy)

    # ---- 0. The policy is subordinate, enforced from ABOVE. -----------------
    check(policy["builds_on"] == "finding-lineage/v1",
          f"the policy must declare what it is subordinate to, got {policy.get('builds_on')!r}")
    check(policy["status"] == "frozen-unimplemented",
          "the policy must declare itself unimplemented until a mapper exists")

    senior_limitations = set(senior["limitations"].values())
    emitted = {v["reason"] for v in policy["reason_mapping"].values()}
    emitted.add(policy["arbitration"]["none_applies"]["reason"])
    emitted.add(policy["arbitration"]["conflict"]["reason"])
    emitted.add(policy["arbitration"]["multiplicity"]["several_candidates_without_one"]["reason"])
    emitted |= {c["reason"] for c in policy["deliberately_unresolved_conflicts"]}
    for reason in sorted(emitted):
        check(reason in senior_limitations,
              f"the policy emits {reason!r}, which finding-lineage/v1 does not define. "
              "Amend the senior contract in the open; do not widen it from below.")

    senior_outcomes = set(senior["outcomes"])
    floor = senior["minimum_evidence_kinds_for_continued"]
    for rid in ids:
        check(outcomes[rid] in senior_outcomes,
              f"{rid} names outcome {outcomes[rid]!r}, which is not one of the six")
        check(outcomes[rid] not in ("ended", "new"),
              f"{rid} licenses {outcomes[rid]!r}; boundary evidence owns that, not a rule")
        if outcomes[rid] == "continued":
            check(len(rules[rid].get("requires_all", [])) >= floor,
                  f"{rid} licenses continued on {len(rules[rid].get('requires_all', []))} "
                  f"kind(s); the frozen floor is {floor}")

    # ---- 1. PAIR COMPLETENESS - an exact cover over DECLARED ids. -----------
    conflicting = {frozenset(p) for p in itertools.combinations(ids, 2)
                   if outcomes[p[0]] != outcomes[p[1]]}
    dominance_pairs = {frozenset(e) for e in edges}
    for pair in sorted(conflicting, key=sorted):
        a, b = sorted(pair)
        in_dom, in_ref = pair in dominance_pairs, pair in refusals
        check(in_dom or in_ref,
              f"{a} and {b} reach different outcomes and neither dominates nor is a "
              "declared refusal - a conflict nobody has looked at")
        check(not (in_dom and in_ref),
              f"{a} and {b} are classified twice, as dominance AND as a deliberate "
              "refusal; a pair has one classification")
    for pair in sorted(dominance_pairs | refusals, key=sorted):
        check(pair in conflicting,
              f"{sorted(pair)} is classified but is not a different-outcome pair of "
              "declared ids; the classification describes nothing")

    # ---- 2. DOMINANCE SANITY ------------------------------------------------
    for (w, l) in sorted(edges):
        check(w in rules, f"dominance names unknown winner {w!r}")
        check(l in rules, f"dominance names unknown loser {l!r}")
        check(w != l, f"{w} dominates itself")
        if w in rules and l in rules:
            check(outcomes[w] != outcomes[l],
                  f"{w} dominates {l} but both name {outcomes[w]!r}; dominance settles "
                  "disagreements, and there is none")
        check((l, w) not in edges, f"{w} and {l} dominate each other")
    check(not has_cycle(ids, edges),
          "the dominance graph has a cycle. Every rule in it is dominated, nothing "
          "survives, and arbitration answers `unresolved` while looking perfectly "
          "well defined - which is why this is checked separately from order "
          "independence, and cannot be caught by it.")

    # ---- 3. TOTALITY - a THEOREM of 1 and 2, re-checked exhaustively. -------
    expected = 2 ** len(ids) - 1
    results = {}
    for size in range(1, len(ids) + 1):
        for sub in itertools.combinations(ids, size):
            results[frozenset(sub)] = arbitrate(sub, outcomes, edges, refusals)
    check(len(results) == expected,
          f"swept {len(results)} subsets, expected {expected} for {len(ids)} rules")
    undefined = sorted((sorted(s) for s, r in results.items() if r is None), key=len)
    check(not undefined,
          f"subsets with no defined result: {undefined[:4]}. The theorem says this "
          "cannot happen while properties 1 and 2 hold, so this failure means one of "
          "them is broken in a way its own check did not catch, or the theorem's "
          "assumptions moved.")

    mismatched = 0
    for subset in results:
        base = results[subset]
        for perm in itertools.islice(itertools.permutations(sorted(subset)), 6):
            if arbitrate(perm, outcomes, edges, refusals) != base:
                mismatched += 1
    check(mismatched == 0, f"{mismatched} subset permutation(s) changed the result")

    for pair in refusals:
        for subset, res in results.items():
            if pair <= subset:
                check(res is not None and res[0] == "unresolved",
                      f"{sorted(subset)} contains the refused pair {sorted(pair)} but "
                      f"resolves to {res}")

    # ---- 4. Structural signals are observable, like boundary evidence. ------
    catalog = policy["structural_signals"]
    for name, spec in catalog.items():
        for field in ("observable_from", "matches", "why"):
            check(field in spec, f"structural signal {name!r} must state {field!r}")
        check(str(spec.get("observable_from", "")).startswith("revision_b."),
              f"structural signal {name!r} must be observable from revision B data, "
              f"got {spec.get('observable_from')!r}")
    for signal, spec in policy["signal_defeaters"].items():
        check(signal in senior["evidence_kinds"],
              f"{signal!r} is defeated by policy but is not a frozen evidence kind")
        check(spec["defeated_by_signal"] in catalog,
              f"{signal!r} is defeated by {spec['defeated_by_signal']!r}, which the "
              "structural signal catalog does not carry")
    for rid in ids:
        for req in rules[rid].get("requires_all", []):
            check(req in senior["evidence_kinds"] or req in catalog,
                  f"{rid} requires {req!r}, which is neither a frozen evidence kind "
                  "nor a catalogued structural signal")

    for f in fails:
        print(f"FAIL: {f}")
    if fails:
        print(f"identity/lineage-decision: FAIL - {len(fails)} check(s) failed")
        return 1
    print(f"identity/lineage-decision: OK - {len(ids)} rules, {len(conflicting)} "
          f"different-outcome pairs all classified, {len(results)} subsets total "
          f"(totality is a theorem of completeness and acyclicity, swept anyway)")
    return 0


def test_lineage_decision() -> None:
    """Pytest entry point; the bare-script path uses `main()` directly."""
    rc = main()
    if rc != 0:
        raise AssertionError(f"lineage decision policy failed: {len(fails)} check(s)")


if __name__ == "__main__":
    raise SystemExit(main())
