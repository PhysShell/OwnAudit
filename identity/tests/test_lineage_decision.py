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

Arbitration is read here the way `arbitration.conflict` states it: remove every
rule some other applicable rule dominates, and the SURVIVORS decide. If they all
name one outcome that is the outcome, and they are all named in `licensed_by`.
Not "one rule dominates all the others" - that is a strictly narrower policy, it
is not what properties 1 and 2 imply, and while the contract said it the sweep
below was proving totality of a policy the contract did not describe.

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

WHAT IS SWEPT, AND WHAT IS NOT
------------------------------
The real policy is verified directly and completely: properties 1 and 2 on its
own declarations, plus the full 2^n - 1 subset sweep of its own rule ids. That
cost is linear in the policy and it stays.

The THEOREM is not re-derived from this policy's classification space. It used
to be - 3^k over the k conflicting pairs - and that was an exponential in k paid
for an argument whose every step quantifies over a subset and a relation and
never mentions k at all. One extra rule took it from 3^7 x 31 = 67797 to
3^9 x 63 = 1240029, so adding an ordinary rule became a CI compute decision.
Instead the theorem is falsified against a FIXED four-rule model (outcomes
partitioned A, A, B, C), sized by this file and not by the policy. The model is
chosen to CONTAIN the shape the survivor reading turns on: two rules of one
outcome surviving together. And it is named for what it is - bounded
falsification, not proof. The proof is the paragraph above; this is a standing
attempt to break it at a size where every classification can be tried.

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

# Reviewed cost ceiling for the theorem falsifier, in arbitrations. It bounds a
# FIXED four-rule model - 3^5 * 15 = 3645 - and not this policy's own
# classification space, so adding a production rule cannot move it. Exceeding it
# is a FAILURE, not a downgrade: see meta-check 5d.
EXHAUSTIVE_PROOF_BUDGET = 250_000

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def raw_dominance_edges(policy: dict) -> list:
    """Occurrences, NOT a set. `classified exactly once` is a claim about the
    declarations, and a set answers a weaker question - it would let
    `loses: ["R-X", "R-X"]` collapse into one edge and pass."""
    return [(p["winner"], loser)
            for p in policy["dominance"]["declared_pairs"]
            for loser in p["loses"]]


def raw_refusal_pairs(policy: dict) -> list:
    return [frozenset(c["between"]) for c in policy["deliberately_unresolved_conflicts"]]


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


def pair_completeness_failures(ids, outcomes, raw_edges, raw_refusals) -> list:
    """PROPERTY 1, as a pure function of a policy shape.

    Pure so the meta-checks below can feed it a deliberately broken policy and
    require it to complain. A property checker that only ever sees the real
    contract is a property checker nobody has tested."""
    out = []
    conflicting = {frozenset(p) for p in itertools.combinations(sorted(ids), 2)
                   if outcomes[p[0]] != outcomes[p[1]]}
    # Exactly once means exactly once, counted BEFORE deduplication.
    for edge in sorted(set(raw_edges)):
        if raw_edges.count(edge) > 1:
            out.append(f"dominance declares {edge[0]} > {edge[1]} {raw_edges.count(edge)} times")
    for pair in sorted({frozenset(r) for r in raw_refusals}, key=sorted):
        if raw_refusals.count(pair) > 1:
            out.append(f"{sorted(pair)} is declared a refusal {raw_refusals.count(pair)} times")
    dominance_pairs = {frozenset(e) for e in raw_edges}
    refusals = {frozenset(r) for r in raw_refusals}
    for pair in sorted(conflicting, key=sorted):
        a, b = sorted(pair)
        in_dom, in_ref = pair in dominance_pairs, pair in refusals
        if not (in_dom or in_ref):
            out.append(f"{a} and {b} reach different outcomes and neither dominates nor "
                       "is a declared refusal - a conflict nobody has looked at")
        if in_dom and in_ref:
            out.append(f"{a} and {b} are classified twice, as dominance AND as a "
                       "deliberate refusal; a pair has one classification")
    for pair in sorted(dominance_pairs | refusals, key=sorted):
        if pair not in conflicting:
            out.append(f"{sorted(pair)} is classified but is not a different-outcome "
                       "pair of declared ids; the classification describes nothing")
    return out


def dominance_sanity_failures(ids, outcomes, raw_edges) -> list:
    """PROPERTY 2, pure for the same reason."""
    out, edges = [], set(raw_edges)
    for (w, l) in sorted(edges):
        if w not in outcomes:
            out.append(f"dominance names unknown winner {w!r}")
        if l not in outcomes:
            out.append(f"dominance names unknown loser {l!r}")
        if w == l:
            out.append(f"{w} dominates itself")
        if w in outcomes and l in outcomes and outcomes[w] == outcomes[l]:
            out.append(f"{w} dominates {l} but both name {outcomes[w]!r}; dominance "
                       "settles disagreements, and there is none")
        if (l, w) in edges:
            out.append(f"{w} and {l} dominate each other")
    if has_cycle(ids, edges):
        out.append("the dominance graph has a cycle. Every rule in it is dominated, "
                   "nothing survives, and arbitration answers `unresolved` while "
                   "looking perfectly well defined - which is why this is checked "
                   "separately from totality and cannot be caught by it.")
    return out


def arbitrate(subset, outcomes, edges, refusals):
    """The contract's procedure, read structurally. Returns (outcome, licensed_by)
    where licensed_by is the SURVIVOR set - empty on a refusal - or None for 'no
    defined result', which the theorem says is unreachable. The sweep is what
    keeps that honest after a future edit."""
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
    raw_edges = raw_dominance_edges(policy)
    raw_refusals = raw_refusal_pairs(policy)
    edges = set(raw_edges)
    refusals = {frozenset(r) for r in raw_refusals}

    # ---- 0. The policy is subordinate, enforced from ABOVE. -----------------
    check(policy["builds_on"] == "finding-lineage/v1",
          f"the policy must declare what it is subordinate to, got {policy.get('builds_on')!r}")
    check(policy["status"] == "frozen-unimplemented",
          "the policy must declare itself unimplemented until a mapper exists")
    # `licensed_by` has ONE definition, and `arbitrate` below implements it. A
    # policy that drops the definition and leaves the branches to imply it is how
    # the survivor reading and the single-winner reading drifted apart the first
    # time.
    check("licensed_by_rule" in policy["arbitration"],
          "`arbitration` must define `licensed_by` once, for every branch; "
          "without it each branch states its own and they drift")
    check("licensed_by_on_refusal" in policy["arbitration"]["conflict"],
          "`arbitration.conflict` must say what `licensed_by` is on a refusal; "
          "empty is a claim, and it has to be written down as one")

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

        # Cardinality is a PRECONDITION of the rule, so it is checked as one. The
        # alternative - letting `arbitration.multiplicity` overturn a structural
        # rule after it fired - puts one question in two sections.
        card = rules[rid].get("cardinality")
        check(isinstance(card, dict) and "shape" in card,
              f"{rid} declares no `cardinality`; a mapper would have to guess whether "
              "the rule is 1:1, and guessing is how a lone successor gets `branched`")
        if isinstance(card, dict):
            shape = card.get("shape")
            if outcomes[rid] == "continued":
                check(shape == "1:1", f"{rid} licenses continued at cardinality {shape!r}; "
                                      "continued is 1:1 in the senior contract")
            elif outcomes[rid] == "branched":
                check(shape == "1:N", f"{rid} licenses branched at {shape!r}")
                check(card.get("min_successors", 0) >= 2,
                      f"{rid} licenses branched without requiring two successors; "
                      "a branch with one is a continued, and the senior contract says so")
            elif outcomes[rid] == "merged":
                check(shape == "N:1", f"{rid} licenses merged at {shape!r}")
                check(card.get("min_predecessors", 0) >= 2,
                      f"{rid} licenses merged without requiring two predecessors")

        # A rule whose cardinality is not 1:1 says something about a GROUP, so it
        # must also say what each partner shows on its own. `a rule of outcome
        # continued` used to stand here and was unsatisfiable on the very frozen
        # cases these rules exist for - see `rules_note`.
        prof = rules[rid].get("partner_profile")
        if isinstance(card, dict) and card.get("shape") != "1:1":
            check(isinstance(prof, dict), f"{rid} is a group rule with no `partner_profile`")
        if prof is not None:
            check(isinstance(prof, dict) and prof.get("per") in ("successor", "predecessor"),
                  f"{rid}: partner_profile must say which side it is `per`")
            req = prof.get("requires_all") if isinstance(prof, dict) else None
            check(isinstance(req, list) and req,
                  f"{rid}: partner_profile must NAME the kinds; the contract refuses to "
                  "derive them, because a derived profile is the floor's cardinal number "
                  "with extra steps")
            if isinstance(req, list):
                for kind in req:
                    check(kind in senior["evidence_kinds"],
                          f"{rid}: partner_profile names {kind!r}, not a frozen evidence kind")
                    check(not senior["evidence_kinds"].get(kind, {}).get("sufficient_alone"),
                          f"{rid}: partner_profile rests on {kind!r}, which is sufficient "
                          "alone; a profile of one strong signal is not a profile")
                check(len(set(req)) == len(req), f"{rid}: partner_profile repeats a kind")
                check(len(set(req)) >= floor,
                      f"{rid}: partner_profile names {len(set(req))} kind(s); the frozen "
                      f"floor is {floor}. The floor is checked, never used to generate.")
        # The abandoned wording must not creep back in under its old names.
        for dead in ("requires_per_successor", "requires_per_predecessor"):
            check(dead not in rules[rid],
                  f"{rid} still carries {dead!r}. That condition was falsified against the "
                  "frozen corpus: every continued rule needs `structural_context`, and the "
                  "copy and fold cases change the enclosing symbol.")

    # ---- 1 and 2, via the pure functions the meta-checks also exercise. -----
    conflicting = {frozenset(p) for p in itertools.combinations(ids, 2)
                   if outcomes[p[0]] != outcomes[p[1]]}
    for msg in pair_completeness_failures(ids, outcomes, raw_edges, raw_refusals):
        check(False, msg)
    for msg in dominance_sanity_failures(ids, outcomes, raw_edges):
        check(False, msg)

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

    # NO PERMUTATION SWEEP. An earlier version ran one and it could not fail:
    # `arbitrate` takes `set(subset)` as its first act, so permuting the argument
    # asked Python whether a set remembers order. It does not, and confirming
    # that 720 times is not evidence about this contract.
    # Order-independence is already carried by the theorem, whose every step is
    # stated over subsets and a relation. What IS worth pinning is that the input
    # is a set of distinct ids in the first place - the shape the argument needs.
    check(all(len(set(sub)) == len(sub) for sub in
              itertools.chain.from_iterable(itertools.combinations(ids, n)
                                            for n in range(1, len(ids) + 1))),
          "arbitration input must be a set of distinct rule ids")

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


    # ---- 5. META: the proof checks are checked, in-process. ----------------
    # a05edeb was titled "move the arbitration proofs out of the terminal" and
    # moved the RESULT while the meta-proofs stayed in scratch scripts. These are
    # those, committed. They break the policy IN MEMORY, which is why the
    # properties above are pure functions rather than inline loops.

    # 5a. Property 1 bites, and property 2 stays green while it does.
    # The mutation drops ONE declared classification of whichever kind the policy
    # happens to carry. An earlier version dropped every refusal, which made the
    # probe an assertion about this policy having refusals: a policy that declared
    # none would have failed here for having nothing to break, and one that later
    # resolved its last refused pair into a dominance edge would have taken the
    # suite red for an improvement.
    if raw_edges:
        mut_edges, mut_refusals, dropped = raw_edges[1:], raw_refusals, "dominance edge"
    elif raw_refusals:
        mut_edges, mut_refusals, dropped = raw_edges, raw_refusals[1:], "refusal"
    else:
        mut_edges, mut_refusals, dropped = None, None, ""
    if mut_edges is None:
        check(not conflicting,
              "the policy declares different-outcome pairs but no classification of "
              "any kind, so property 1 cannot be probed by removing one")
    else:
        check(bool(pair_completeness_failures(ids, outcomes, mut_edges, mut_refusals)),
              f"dropping one declared {dropped} left pair completeness satisfied; "
              "the check does not bite")
        check(not dominance_sanity_failures(ids, outcomes, mut_edges),
              f"dropping one declared {dropped} also tripped dominance sanity; the "
              "two properties are supposed to be independent")

    # 5b. Property 2 bites, and property 1 stays green while it does.
    cyc_ids = [r for r in ids if outcomes[r] == "continued"][:1] + \
              [r for r in ids if outcomes[r] == "branched"][:1] + \
              [r for r in ids if outcomes[r] == "merged"][:1]
    if len(cyc_ids) == 3:
        a, b, c = cyc_ids
        others = [r for r in ids if r not in cyc_ids]
        cyc_edges = [(a, b), (b, c), (c, a)]
        # every remaining conflicting pair still classified, so property 1 holds
        for x in others:
            for y in (a, b, c):
                if outcomes[x] != outcomes[y]:
                    cyc_edges.append((y, x) if outcomes[y] != "continued" else (x, y))
        for x, y in itertools.combinations(others, 2):
            if outcomes[x] != outcomes[y]:
                cyc_edges.append((x, y))
        check(bool(dominance_sanity_failures(ids, outcomes, cyc_edges)),
              "a three-cycle did not trip dominance sanity")
        check(not pair_completeness_failures(ids, outcomes, cyc_edges, []),
              "the three-cycle construction also broke pair completeness, so it does "
              "not show the two properties are independent")

    # 5c. Duplicate declarations are caught BEFORE deduplication.
    check(bool(pair_completeness_failures(ids, outcomes, raw_edges + raw_edges[:1],
                                          raw_refusals)),
          "a dominance edge declared twice was absorbed by a set and passed; "
          "`classified exactly once` is a claim about the declarations")
    if raw_refusals:
        check(bool(pair_completeness_failures(ids, outcomes, raw_edges,
                                              raw_refusals + raw_refusals[:1])),
              "a refusal declared twice was absorbed by a set and passed")

    # 5d. THE THEOREM, falsified against a FIXED model.
    # Not an enumeration of this policy's classification space. That is what used
    # to be here, and it was an exponential in k paid for a theorem whose proof
    # never mentions k: adding one ordinary rule took 3^7 x 31 = 67797 to
    # 3^9 x 63 = 1240029 and fired the budget, turning `write a sixth rule` into
    # `revise the CI compute policy`.
    # The real policy is verified directly and completely above. What is enumerated
    # here is a four-rule model whose outcomes partition A, A, B, C - chosen because
    # it CONTAINS the case the survivor reading turns on, two rules of one outcome
    # surviving together. Its cost is a constant of this file.
    model_outcomes = {"M-A1": "A", "M-A2": "A", "M-B": "B", "M-C": "C"}
    model_ids = sorted(model_outcomes)
    model_pairs = [tuple(sorted(pr)) for pr in
                   sorted(({frozenset(x) for x in itertools.combinations(model_ids, 2)
                            if model_outcomes[x[0]] != model_outcomes[x[1]]}), key=sorted)]
    mk = len(model_pairs)
    model_space = 3 ** mk
    model_cost = model_space * (2 ** len(model_ids) - 1)
    check(model_cost <= EXHAUSTIVE_PROOF_BUDGET,
          f"the theorem model costs {model_cost} arbitrations, over the reviewed budget "
          f"of {EXHAUSTIVE_PROOF_BUDGET}. This model is a constant of this file, so "
          "exceeding it means the model was edited, not that the policy grew.")
    satisfying, counterexamples, saw_multi_survivor = 0, [], False
    for combo in itertools.product((0, 1, 2), repeat=mk):
        e, rf = [], []
        for (x, y), state in zip(model_pairs, combo):
            if state == 0:
                e.append((x, y))
            elif state == 1:
                e.append((y, x))
            else:
                rf.append(frozenset((x, y)))
        if pair_completeness_failures(model_ids, model_outcomes, e, rf):
            continue
        if dominance_sanity_failures(model_ids, model_outcomes, e):
            continue
        satisfying += 1
        es, rs = set(e), set(rf)
        for n in range(1, len(model_ids) + 1):
            for sub in itertools.combinations(model_ids, n):
                res = arbitrate(sub, model_outcomes, es, rs)
                if res is None:
                    counterexamples.append((combo, sub))
                elif len({model_outcomes[r] for r in sub}) > 1 and len(res[1]) > 1:
                    saw_multi_survivor = True
    check(satisfying > 0,
          f"no classification of the model's {mk} pairs satisfied both axioms; the "
          "falsifier is not exercising anything")
    check(not counterexamples,
          f"totality is NOT a theorem of the two axioms: {len(counterexamples)} "
          f"counterexample(s), first {counterexamples[:1]}. The contract claims a "
          "proof it does not have.")
    # The model has to contain the interesting shape, or it is a cheaper check of
    # a weaker claim wearing the same name.
    check(saw_multi_survivor,
          "no classification of the model produced a disagreeing subset whose SURVIVORS "
          "were several rules of one outcome. That shape is the whole reason this model "
          "has two rules of outcome A, and without it the falsifier would pass for a "
          "policy using the abandoned `exactly one dominating rule` reading.")
    print(f"       theorem: bounded falsification on a fixed 4-rule model - {satisfying} "
          f"of {model_space} classifications satisfy both axioms, 0 break totality "
          f"({model_cost} arbitrations, independent of the {len(ids)} production rules)")

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
