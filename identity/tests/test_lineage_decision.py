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
sweep is EXPONENTIAL in the rule count - six rules sweep 63 subsets, twelve sweep
4095 - and it carries a reviewed ceiling that fails CI rather than growing
quietly. An earlier revision of this docstring called it linear while the code
below said the opposite in the same file, which is worse than either claim alone.

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
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SENIOR = os.path.join(ROOT, "contracts", "finding-lineage-v1.json")
POLICY = os.path.join(ROOT, "contracts", "finding-lineage-decision-v1.json")
FIXDIR = os.path.join(ROOT, "identity", "fixtures", "lineage-decision")
DOC = os.path.join(ROOT, "docs", "finding-lineage-decision.md")

# Reviewed cost ceiling for the theorem falsifier, in arbitrations. It bounds a
# FIXED four-rule model - 3^5 * 15 = 3645 - and not this policy's own
# classification space, so adding a production rule cannot move it. Exceeding it
# is a FAILURE, not a downgrade: see meta-check 5d.
EXHAUSTIVE_PROOF_BUDGET = 250_000

# Reviewed ceiling for the REAL-POLICY subset sweep, in subsets. This one IS
# exponential in the rule count - 2^n - 1, every subset enumerated and retained.
# What the previous commit removed was the 3^k factor in front of it, not the
# exponential itself, and calling the remainder "linear" was simply wrong: six
# rules sweep 63 subsets, twelve sweep 4095, twenty sweep over a million.
# So it gets the same treatment as the falsifier - a reviewed ceiling that fails
# CI rather than a claim that the cost is fine. 4095 is twelve rules, which is
# double the current set and still trivial to run.
SUBSET_SWEEP_BUDGET = 4095

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def duplicate_json_keys(path: str) -> list:
    """Keys declared twice in ONE object, found during the RAW parse.

    Has to be its own read: `json.load` resolves duplicates by keeping the last,
    so nothing downstream can tell a duplicated key from a single one.

    Each entry names the key AND the other keys of the object holding it, because
    the bare name is not enough to find it - `reason` appears in a dozen places in
    the policy. An earlier docstring promised "dotted paths" while the code
    returned bare names, which is the same defect these rounds keep finding one
    layer up: a description claiming more than the code does. `object_pairs_hook`
    is called innermost-first and never learns where it is, so the siblings are
    what can honestly be offered, and the docstring says that instead."""
    dups: list = []

    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                siblings = sorted({k for k, _ in pairs} - {key})
                dups.append(f"{key!r} (in an object also declaring "
                            f"{', '.join(siblings) or 'nothing else'})")
            seen.add(key)
        return dict(pairs)

    with open(path, encoding="utf-8") as fh:
        json.load(fh, object_pairs_hook=hook)
    return sorted(set(dups))


def rule_needs(rule) -> set:
    """Every signal a rule needs to apply - group requirements AND the per-partner
    profile.

    Reading `requires_all` alone missed the profile entirely, so declaring
    `same_pattern_id` unavailable left `R-BRANCH-COPY` applicable although every
    successor profile requires it: evidence that could not be evaluated was
    licensing a resolved mapping. The defeat path had the same omission; it was
    not independently demonstrable on the current fixtures, because in every case
    where a defeatable signal reaches a group rule's profile it also sits in some
    applicable 1:1 rule's `requires_all` and is caught there first. Same code
    path, same fix, and only one half has a witness."""
    needs = set(rule.get("requires_all") or [])
    profile = rule.get("partner_profile") or {}
    return needs | set(profile.get("requires_all") or [])


def mandated_reason(exp, mapping, floor):
    """The reason the policy REQUIRES for this refusal, or None if the contract
    has not settled the shape.

    READ FROM `reason_mapping`, not from the senior vocabulary directly. An
    earlier version picked limitation values by name and then told the reader
    `reason_mapping mandates X` - a message claiming an authority the code never
    consulted. Swapping the values the policy assigns to `no_rule_applied` and
    `several_candidates` left the suite green, because the vocabulary sweep only
    compares the resulting SET while fixtures were judged against the hard-coded
    associations here.

    Derived from what the fixture DECLARES about its own stages - not from any
    evidence reasoning. None means deliberately unmandated, and the caller fails
    on it rather than guessing: a shape nobody has ranked must not be settled by
    whichever condition was typed first."""
    def of(key, surviving_kinds=None):
        spec = mapping.get(key) or {}
        if "reason" in spec:
            return spec["reason"]
        by = spec.get("reason_by_surviving_kinds") or {}
        if surviving_kinds is None:
            return None
        return by.get("below_the_floor" if surviving_kinds < floor
                      else "at_or_above_the_floor")

    app = exp.get("applicable_rules") or []
    defeated = exp.get("signals_defeated") or {}
    unavailable = as_list(exp.get("inputs_unavailable"))
    detail = exp.get("decision_detail") or {}
    blunted = detail.get("rules_without_a_unique_candidate") or []
    miscard = detail.get("rules_excluded_by_cardinality") or []

    if app:
        # Rules applied and the answer is still a refusal: they disagreed.
        return of("conflicting_rules"), "rules applied and disagreed"
    # More than one rejecting stage fired at once. Each has its own reason and
    # the contract does not rank them; picking one here would be this file
    # deciding a contract question in a checker.
    stages = [bool(defeated), bool(unavailable), bool(blunted), bool(miscard)]
    if sum(stages) > 1:
        return None, "several rejecting stages fired; the contract has not ranked them"
    if defeated:
        n = len({k for k in (exp.get("evidence_surviving") or [])})
        return (of("no_rule_applied_after_a_defeat", n),
                f"a defeat left {n} kind(s) against a floor of {floor}")
    if blunted:
        return of("several_candidates"), "rules matched and singled nobody out"
    if unavailable:
        return of("no_rule_applied"), "a signal could not be evaluated"
    if miscard:
        return of("no_rule_applied"), "the only matches were the wrong shape"
    return of("no_rule_applied"), "nothing matched at all"


def as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def collect(rev: dict, dotted: str) -> list:
    """Read `revision_b.field[].sub` out of a fixture. Lifted from the step 0
    suite deliberately: `the fixture must CARRY the fact` is the same rule here,
    and a second, subtly different reader would be a second rule."""
    head, _, rest = dotted.partition(".")
    if head != "revision_b":
        return []
    field, _, sub = rest.partition("[].")
    raw = rev.get(field, [])
    if not sub:
        return [x for x in raw if isinstance(x, str)]
    out = []
    for entry in raw:
        if isinstance(entry, dict) and sub in entry:
            val = entry[sub]
            out.extend(val if isinstance(val, list) else [val])
    return out


def signal_bindings(spec: dict) -> list:
    """(read path, subject role, subject attribute) for each key the catalog's
    `matches` names.

    `matches` is the NORMATIVE half and `entry_shape` only says how the entries
    are shaped. An earlier version read every key of `entry_shape`, which is a
    strictly wider and wrong semantics: `renamed_symbol_record` matches on `from`
    alone, so pooling `from` and `to` let a record reading
    `Other.Symbol -> DocView.Wire` defeat a predecessor in DocView.Wire - the
    rename record says something arrived at that name, which is the opposite of
    the evidence the defeat needs."""
    field = str(spec.get("observable_from", ""))
    shape = spec.get("entry_shape")
    out = []
    for key, subject in (spec.get("matches") or {}).items():
        role, _, attr = str(subject).partition(".")
        read = f"{field}[].{key}" if isinstance(shape, dict) else field
        out.append((read, role, attr))
    return out


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
    for (w, loser) in sorted(edges):
        if w not in outcomes:
            out.append(f"dominance names unknown winner {w!r}")
        if loser not in outcomes:
            out.append(f"dominance names unknown loser {loser!r}")
        if w == loser:
            out.append(f"{w} dominates itself")
        if w in outcomes and loser in outcomes and outcomes[w] == outcomes[loser]:
            out.append(f"{w} dominates {loser} but both name {outcomes[w]!r}; dominance "
                       "settles disagreements, and there is none")
        if (loser, w) in edges:
            out.append(f"{w} and {loser} dominate each other")
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
    # A mapping entry declares EITHER one reason or a conditional set of them.
    # `no_rule_applied_after_a_defeat` became conditional when a defeat leaving
    # fewer kinds than the floor turned out to need the other limitation, so the
    # sweep reads both shapes - and requires exactly one of them, because an entry
    # carrying both would emit a value nothing selects.
    emitted = set()
    for key, spec in policy["reason_mapping"].items():
        single, conditional = "reason" in spec, "reason_by_surviving_kinds" in spec
        check(single != conditional,
              f"reason_mapping[{key}] must declare exactly one of `reason` or "
              "`reason_by_surviving_kinds`, not both and not neither")
        if single:
            emitted.add(spec["reason"])
        if conditional:
            emitted |= {v for k, v in spec["reason_by_surviving_kinds"].items()
                        if str(v).startswith("lineage-id-unavailable:")}
    emitted.add(policy["arbitration"]["none_applies"]["reason"])
    emitted.add(policy["arbitration"]["conflict"]["reason"])
    emitted.add(policy["arbitration"]["multiplicity"]["several_candidates_without_one"]["reason"])
    emitted |= {c["reason"] for c in policy["deliberately_unresolved_conflicts"]}
    for reason in sorted(emitted):
        check(reason in senior_limitations,
              f"the policy emits {reason!r}, which finding-lineage/v1 does not define. "
              "Amend the senior contract in the open; do not widen it from below.")

    # A DECLARED REFUSAL MUST SAY WHAT THE ALGEBRA DOES. `raw_refusal_pairs` reads
    # only `between`, and `arbitrate` hard-codes `unresolved`, so the entry's own
    # `outcome` and `reason` were decoration: turning the frozen N:M entry into
    # `outcome: continued` with a no-mapping-evidence reason left the suite green
    # while that entry, `arbitration.conflict` and `reason_mapping.conflicting_rules`
    # all disagreed.
    # ONE REASON, DECLARED THREE TIMES. Each arbitration branch names the
    # `reason_mapping` entry it implements, and the two must agree. Nothing tied
    # them together before: repointing `arbitration.conflict.reason` - or
    # `none_applies`, or the multiplicity branch, all three were loose - left the
    # suite green while a mapper implementing from that section would emit a value
    # the mapping and every fixture reject.
    branches = [(("arbitration", "none_applies"), policy["arbitration"]["none_applies"]),
                (("arbitration", "conflict"), policy["arbitration"]["conflict"]),
                (("arbitration", "multiplicity", "several_candidates_without_one"),
                 policy["arbitration"]["multiplicity"]["several_candidates_without_one"])]
    for where_b, node in branches:
        key = node.get("implements")
        check(key in policy["reason_mapping"],
              f"{'.'.join(where_b)} names reason {node.get('reason')!r} and implements "
              f"{key!r}, which is not a `reason_mapping` entry. The correspondence is "
              "declared, not guessed - a checker that knows which branch means which "
              "entry has an opinion nobody can review.")
        if key in policy["reason_mapping"]:
            want_b = (policy["reason_mapping"][key] or {}).get("reason")
            check(node.get("reason") == want_b,
                  f"{'.'.join(where_b)} says {node.get('reason')!r} but implements "
                  f"{key!r}, which selects {want_b!r}. One value, stated three times, "
                  "and all three have to say it.")

    conflict_reason = (policy["reason_mapping"].get("conflicting_rules") or {}).get("reason")
    for entry in policy["deliberately_unresolved_conflicts"]:
        pair = sorted(entry.get("between") or [])
        check(entry.get("outcome") == "unresolved",
              f"declared refusal {pair} names outcome {entry.get('outcome')!r}. Arbitration "
              "answers `unresolved` on a refused pair and nothing else reads this field, "
              "so any other value is a claim the algebra contradicts.")
        check(entry.get("reason") == conflict_reason,
              f"declared refusal {pair} names reason {entry.get('reason')!r}, but "
              f"`reason_mapping.conflicting_rules` selects {conflict_reason!r}. One "
              "authority, or a mapper reads whichever it happened to open.")

    senior_outcomes = set(senior["outcomes"])
    floor = senior["minimum_evidence_kinds_for_continued"]
    for rid in ids:
        check(outcomes[rid] in senior_outcomes,
              f"{rid} names outcome {outcomes[rid]!r}, which is not one of the six")
        check(outcomes[rid] not in ("ended", "new"),
              f"{rid} licenses {outcomes[rid]!r}; boundary evidence owns that, not a rule")
        # The floor counts KINDS, so the check must too. Counting list length let
        # `["same_path", "same_path"]` clear a floor of two with one real kind -
        # in the same file whose whole argument is that the floor is a floor.
        # `partner_profile` already got this right; `requires_all` did not.
        req_all = rules[rid].get("requires_all", [])
        check(len(set(req_all)) == len(req_all),
              f"{rid}: requires_all repeats a kind. The floor counts kinds, so a "
              "repeat is either a typo or an attempt to reach the floor twice over "
              "the same evidence.")
        if outcomes[rid] == "continued":
            check(len(set(req_all)) >= floor,
                  f"{rid} licenses continued on {len(set(req_all))} distinct "
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
    # Exponential, and budgeted for it. See SUBSET_SWEEP_BUDGET.
    expected = 2 ** len(ids) - 1
    if expected > SUBSET_SWEEP_BUDGET:
        check(False,
              f"the real-policy subset sweep needs 2^{len(ids)} - 1 = {expected} "
              f"subsets, over the reviewed ceiling of {SUBSET_SWEEP_BUDGET}. This sweep "
              "is exponential in the rule count - it always was, and the k-independent "
              "argument only removed the 3^k factor in front of it. Either raise the "
              "reviewed ceiling or rely on the written proof instead of re-checking it "
              "by enumeration. Do not skip it silently.")
        expected = 0
    results = {}
    if expected:
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
    # stated over subsets and a relation.
    #
    # A REPLACEMENT THAT WAS ALSO VACUOUS. The first attempt at "something worth
    # pinning" checked that every swept subset holds distinct ids - and
    # `itertools.combinations` never repeats an element, so it asked Python a
    # question with one possible answer. Removing a vacuous check and installing
    # another one under a comment about vacuous checks is worse than leaving the
    # first: it looks like the lesson was learned.
    # `len(set(ids)) == len(ids)` would be vacuous too, one step later: `json.load`
    # collapses duplicate object keys silently, so by the time the ids are a dict
    # the duplicate is already gone - along with one of the two rules.
    # What CAN fail is the raw parse, so that is what is checked, on the contracts
    # that carry rules and vocabulary this suite reads by key.
    scanned = [("decision policy", POLICY), ("outcome contract", SENIOR)]
    # ...and the FIXTURES, which this suite also reads by key. A case declaring
    # `licensed_by` twice loses one to `json.load` in the same silent way, and the
    # case is then checked against half of what it says - verified: the first
    # declaration vanishes and the suite stays green.
    scanned += [(f"fixture {f}", os.path.join(FIXDIR, f))
                for f in sorted(os.listdir(FIXDIR)) if f.endswith(".json")]
    for label, cpath in scanned:
        for dup in duplicate_json_keys(cpath):
            check(False,
                  f"the {label} declares {dup} twice. `json.load` keeps the last one "
                  "and drops the other without a word, so a rule, a limitation, an "
                  "evidence kind or half a preregistered expectation would vanish "
                  "between the file and every check below.")

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


    # ---- 4b. THE PREREGISTERED MATRIX. --------------------------------------
    # Not a mapper test. This suite never decides which rules a real evidence
    # record produces - that is applicability, and a checker doing it becomes a
    # second mapper. What it checks is that each case's DECLARED rule set agrees
    # with the arbitration algebra, that every id and reason exists, and that a
    # claimed record is actually carried by the fixture rather than by prose.
    preregistered = policy["preregistered_cases"]
    on_disk = sorted(f[:-5] for f in os.listdir(FIXDIR) if f.endswith(".json"))
    check(on_disk == sorted(preregistered),
          "the decision fixture matrix drifted from the preregistered list.\n"
          f"  on disk:       {on_disk}\n"
          f"  preregistered: {sorted(preregistered)}\n"
          "  A case may be ADDED with its contract entry. None may be removed or "
          "renamed to make an implementation look better - and trying to write the "
          "first two is what falsified the rule set, so partial credit is not on offer.")

    senior_limitations_set = set(senior["limitations"].values())
    unavailable_from = str(policy["unavailable_inputs"].get("observable_from", ""))
    check(unavailable_from.startswith("revision_b."),
          "`unavailable_inputs.observable_from` must name a revision B field, got "
          f"{unavailable_from!r}")
    obligations = policy["case_obligations"]["obligations"]
    obligation_meanings = policy["case_obligations"]["meanings"]
    check(sorted(obligations) == sorted(preregistered),
          "`case_obligations` and `preregistered_cases` disagree:\n"
          f"  obligations:   {sorted(obligations)}\n"
          f"  preregistered: {sorted(preregistered)}")
    for cname, duties in obligations.items():
        check(bool(duties), f"{cname}: an empty obligation list says nothing")
        for duty in duties:
            check(duty in obligation_meanings,
                  f"{cname}: obligation {duty!r} has no entry in `meanings`")
    licensed_outcomes: set[str] = set()
    exercised_refusals: set = set()
    for name in sorted(set(on_disk) & set(preregistered)):
        with open(os.path.join(FIXDIR, f"{name}.json"), encoding="utf-8") as fh:
            case = json.load(fh)
        check(case.get("case") == name, f"{name}: case field is {case.get('case')!r}")
        check(case.get("contract") == "finding-lineage-decision/v1",
              f"{name}: wrong contract {case.get('contract')!r}")
        check(case.get("status") == "preregistered-unimplemented",
              f"{name}: a decision fixture stays preregistered until a mapper exists")
        check(len(case.get("why", "")) > 40, f"{name}: `why` must state what the case defends")
        check(bool(case.get("expect")), f"{name}: nothing is preregistered")

        rev_a, rev_b = case.get("revision_a", {}), case.get("revision_b", {})
        occ_a = {o["occurrence_id"] for o in rev_a.get("occurrences", [])}
        occ_b = {o["occurrence_id"] for o in rev_b.get("occurrences", [])}
        by_id = {o["occurrence_id"]: o for o in
                 rev_a.get("occurrences", []) + rev_b.get("occurrences", [])}
        claimed_a, claimed_b = set(), set()

        for i, exp in enumerate(case.get("expect", [])):
            where = f"{name}[{i}]"
            outcome = exp.get("outcome")
            check(outcome in senior_outcomes,
                  f"{where}: outcome {outcome!r} is not in the frozen vocabulary")
            frm, to = as_list(exp.get("frm")), as_list(exp.get("to"))
            claimed_a.update(frm)
            claimed_b.update(to)
            for o in frm:
                check(o in occ_a, f"{where}: predecessor {o!r} is not in revision A")
            for o in to:
                check(o in occ_b, f"{where}: successor {o!r} is not in revision B")

            app = exp.get("applicable_rules")
            lic = exp.get("licensed_by")
            check(isinstance(app, list) and isinstance(lic, list),
                  f"{where}: a decision fixture must declare applicable_rules and licensed_by")
            if not (isinstance(app, list) and isinstance(lic, list)):
                continue
            for rid in app + lic:
                check(rid in rules, f"{where}: names unknown rule {rid!r}")
            check(len(set(app)) == len(app), f"{where}: applicable_rules repeats an id")
            # `licensed_by` is a SET of surviving rules in the contract, and every
            # validation here normalised it through `set(lic)` - so a repeat passed
            # and the corpus sanctioned two raw shapes for one provenance record.
            # The uniqueness was checked for one field and not its twin, again.
            check(len(set(lic)) == len(lic), f"{where}: licensed_by repeats an id")
            check(set(lic) <= set(app),
                  f"{where}: licensed_by {sorted(set(lic) - set(app))} is not in "
                  "applicable_rules; a rule cannot license what it never applied to")
            licensed_outcomes.add(outcome)
            for _pair in refusals:
                if _pair <= set(app):
                    exercised_refusals.add(_pair)

            # THE BINDING CHECK. Applicability is the fixture's to declare;
            # arbitration is mechanical, so the fixture may not disagree with it.
            if all(rid in rules for rid in app):
                if not app:
                    check(outcome == "unresolved",
                          f"{where}: no rule applied, so the outcome is unresolved")
                    check(not lic, f"{where}: nothing applied, so nothing licensed")
                    # AN EMPTY SET IS NOT ONE SITUATION - nothing matched, and
                    # everything matched but singled nobody out, are different
                    # refusals. WHICH reason each requires is decided in exactly one
                    # place, `mandated_reason`, and used at the unresolved branch
                    # below. A per-branch mandate used to sit here too, and the two
                    # then contradicted each other: uniqueness plus a defeat made
                    # the suite UNSATISFIABLE - this check demanded
                    # `ambiguous-candidates` while the defeat check demanded an
                    # insufficiency reason, so no value could pass - and uniqueness
                    # plus cardinality quietly re-imposed the very ranking
                    # `mandated_reason` exists to refuse.
                else:
                    got = arbitrate(app, outcomes, edges, refusals)
                    check(got is not None, f"{where}: arbitration has no result for {sorted(app)}")
                    if got is not None:
                        check(got[0] == outcome,
                              f"{where}: declares {outcome!r}, but arbitrating {sorted(app)} "
                              f"yields {got[0]!r}. The fixture and the algebra must not "
                              "describe two different policies.")
                        check(set(lic) == set(got[1]),
                              f"{where}: declares licensed_by {sorted(lic)}, but the surviving "
                              f"rules are {sorted(got[1])}")

            # Cardinality is a precondition, so the shape must match what licensed it.
            for rid in lic:
                card = rules[rid].get("cardinality", {})
                shape = card.get("shape")
                if shape == "1:1":
                    check(len(frm) == 1 and len(to) == 1,
                          f"{where}: {rid} is 1:1 but licenses {len(frm)}:{len(to)}")
                elif shape == "1:N":
                    check(len(frm) == 1 and len(to) >= card.get("min_successors", 2),
                          f"{where}: {rid} is 1:N with min {card.get('min_successors')} "
                          f"but licenses {len(frm)}:{len(to)}")
                elif shape == "N:1":
                    check(len(to) == 1 and len(frm) >= card.get("min_predecessors", 2),
                          f"{where}: {rid} is N:1 with min {card.get('min_predecessors')} "
                          f"but licenses {len(frm)}:{len(to)}")

            # NOTHING MAY BE DROPPED IN SILENCE - the occurrence-accounting rule,
            # applied to rules. Every declared rule must be accounted for by name:
            # applicable, explicitly not applicable with a reason, or recorded as
            # having failed to single out a candidate. A rule nobody mentions is
            # indistinguishable from one the case author forgot existed, and that
            # is precisely how R-CONT-COPY stayed missing.
            # Mirror sides (`side: b`) are exempt: they restate the other half of a
            # refusal already accounted for and raise no new rule question.
            if exp.get("side") != "b":
                # BOTH rejecting stages count as an account of a rule. Listing only
                # the uniqueness one meant a fixture recording a rule solely under
                # the new cardinality stage was reported as never mentioning it -
                # hidden today only because the copy fixture repeats that rule in
                # `not_applicable` as well.
                _dd = exp.get("decision_detail") or {}
                named = (set(app) | set(exp.get("not_applicable") or {})
                         | set(_dd.get("rules_without_a_unique_candidate") or [])
                         | set(_dd.get("rules_excluded_by_cardinality") or []))
                check(named >= set(ids),
                      f"{where}: says nothing about {sorted(set(ids) - named)}. Every rule "
                      "must be accounted for - applicable, not applicable with a reason, or "
                      "unable to choose.")

            for rid, reason in (exp.get("not_applicable") or {}).items():
                check(rid in rules, f"{where}: not_applicable names unknown rule {rid!r}")
                check(rid not in app,
                      f"{where}: {rid} is in applicable_rules AND not_applicable")
                check(isinstance(reason, str) and len(reason) > 10,
                      f"{where}: not_applicable[{rid}] must say WHY, not just list the id")

            if outcome == "unresolved":
                check(exp.get("side") in ("a", "b"),
                      f"{where}: unresolved needs side 'a' or 'b', got {exp.get('side')!r}")
                # THE RAW SHAPE, BEFORE `as_list` FLATTENS IT. finding-lineage/v1
                # describes the two sides asymmetrically - side a "leaves `to`
                # empty", side b "leaves `frm` null" - and its own corpus follows
                # that exactly. This matrix wrote `frm: []` on every b side, and
                # `as_list` normalised the difference away, so a preregistered case
                # was teaching a shape the senior contract does not sanction to any
                # mapper or schema consumer reading it.
                if exp.get("side") == "b":
                    check(exp.get("frm", "missing") is None,
                          f"{where}: an unresolved(b) leaves `frm` NULL per "
                          f"finding-lineage/v1, got {exp.get('frm', 'missing')!r}. An "
                          "empty list is a different claim, and normalising it here "
                          "would hide the divergence rather than allow it.")
                else:
                    check(exp.get("to") == [],
                          f"{where}: an unresolved(a) leaves `to` EMPTY per "
                          f"finding-lineage/v1, got {exp.get('to')!r}")
                check(exp.get("reason") in senior_limitations_set,
                      f"{where}: reason {exp.get('reason')!r} is not a senior limitation")
                check(not lic, f"{where}: a refusal licenses nothing")
                # AND it must be the reason the POLICY BRANCH mandates. Vocabulary
                # membership alone accepted any of the six - `missing-occurrence-id`
                # passed on a case whose occurrences both carry ids.
                want, why_branch = mandated_reason(exp, policy["reason_mapping"], floor)
                if want is None:
                    # FAIL-CLOSED on an unranked shape. Abstaining was the right call
                    # for a CHECKER - the contract has not ranked these stages, so
                    # picking one here would settle a contract question in a test.
                    # But letting the case through unchecked is the other half of the
                    # same mistake: it preregisters an answer nothing licenses.
                    check(False,
                          f"{where}: {why_branch}. No reason can be mandated, so this "
                          "shape must not be preregistered yet. Rank the stages in "
                          "`reason_mapping` first, then write the case - a fixture is "
                          "how a decision gets frozen, not how one gets skipped.")
                else:
                    check(exp.get("reason") == want,
                          f"{where}: {why_branch}, so `reason_mapping` mandates {want!r}, "
                          f"not {exp.get('reason')!r}")
            else:
                check("reason" not in exp,
                      f"{where}: {outcome} must not carry an identity limitation")
                check(bool(lic), f"{where}: {outcome} must name what licensed it")

            # A defeat must be CARRIED by revision B, exactly as a boundary is.
            for signal, source in (exp.get("signals_defeated") or {}).items():
                spec = policy["signal_defeaters"].get(signal)
                check(spec is not None,
                      f"{where}: {signal!r} is not a defeatable signal in the policy")
                if spec is None:
                    continue
                check(spec["defeated_by_signal"] == source or
                      catalog.get(spec["defeated_by_signal"], {}).get("observable_from", "")
                      .endswith("." + str(source)),
                      f"{where}: {signal!r} is defeated by {spec['defeated_by_signal']!r}, "
                      f"not by {source!r}")
                cat = catalog.get(spec["defeated_by_signal"], {})
                bindings = signal_bindings(cat)
                check(bool(bindings),
                      f"{where}: {spec['defeated_by_signal']!r} declares no `matches`, so "
                      "there is nothing to check the record against")
                # The record must name THIS occurrence, on the key the catalog says
                # it matches on. A record about another symbol in the same file
                # defeats nothing - which is the trap
                # `renamed-symbol-defeats-structural-context` is built out of.
                for read, role, attr in bindings:
                    observed = collect(rev_b, read)
                    check(bool(observed),
                          f"{where}: claims {signal!r} was defeated, but {read} carries "
                          "nothing to match on. A defeat asserted in a note is a note.")
                    subject_ids = frm if role == "predecessor" else to
                    for oid in subject_ids:
                        wanted = by_id.get(oid, {}).get(attr)
                        check(wanted in observed,
                              f"{where}: {spec['defeated_by_signal']!r} matches on {read} "
                              f"= {role}.{attr}, which for {oid} is {wanted!r}; the record "
                              f"holds {sorted(observed)!r} and so defeats nothing here")
                for rid in app:
                    check(signal not in rule_needs(rules[rid]),
                          f"{where}: {rid} is applicable but requires the defeated "
                          f"signal {signal!r}")

            # THE TWO NEIGHBOURS, kept apart mechanically. `insufficient-evidence-
            # kind` means the senior floor was not cleared; `-combination` means it
            # was and no declared combination survives. Without this the fixture
            # could name either and the suite would shrug, because both are valid
            # senior limitations - and the whole point of
            # `defeated-signal-drops-below-the-floor` is which one is true.
            surviving = exp.get("evidence_surviving")
            if exp.get("signals_defeated"):
                check(isinstance(surviving, list),
                      f"{where}: a defeat must declare `evidence_surviving` - what is "
                      "left standing is what decides which limitation is honest")
            if isinstance(surviving, list):
                for kind in surviving:
                    check(kind in senior["evidence_kinds"],
                          f"{where}: evidence_surviving names {kind!r}, not a frozen kind")
                for kind in (exp.get("signals_defeated") or {}):
                    check(kind not in surviving,
                          f"{where}: {kind!r} is both defeated and surviving")
                reason = exp.get("reason")
                # `.get`, not `[...]`: a missing senior key is a real situation - the
                # vocabulary check above is what diagnoses it - and crashing here
                # would replace that diagnosis with a traceback. A suite that dies on
                # the evidence it came to read has happened in this repo before.
                lim = senior["limitations"]
                # WHICH reason a defeat requires is `mandated_reason`'s decision,
                # made once and applied at the unresolved branch. What is left here
                # is ARITHMETIC: whatever reason the fixture declares must be
                # consistent with the count it declares. That holds no matter which
                # stages fired, so it is safe next to a single authority - a second
                # mandate was not.
                if reason == lim.get("insufficient-evidence-kind"):
                    check(len(set(surviving)) < floor,
                          f"{where}: claims insufficient KINDS, but {len(set(surviving))} "
                          f"survive against a floor of {floor}. The kinds are ample; it is "
                          "the combination that no rule accepts.")
                if reason == lim.get("insufficient-evidence-combination"):
                    check(len(set(surviving)) >= floor,
                          f"{where}: claims insufficient COMBINATION, but only "
                          f"{len(set(surviving))} kind(s) survive against a floor of "
                          f"{floor}. Below the floor the shortage really is of kinds.")

            for sig in as_list(exp.get("inputs_unavailable")):
                check(sig in senior["evidence_kinds"] or sig in catalog,
                      f"{where}: unavailable input {sig!r} is neither a frozen evidence "
                      "kind nor a catalogued structural signal")
                # Read from the field the CONTRACT declares, not a name hardcoded
                # here. A hardcoded reader leaves `observable_from` decorative:
                # changing it would break nothing, which is the same defect as a
                # boundary that lives only in prose.
                declared = collect(rev_b, unavailable_from)
                check(sig in declared,
                      f"{where}: claims {sig!r} was unavailable, but {unavailable_from} "
                      f"holds {declared!r}. Unavailability is a RECORD, which is the "
                      "entire point of the case.")
                for rid in app:
                    check(sig not in rule_needs(rules[rid]),
                          f"{where}: {rid} is applicable but requires the unevaluable "
                          f"signal {sig!r}")

            # Both rejecting stages are recorded, and neither may overlap the set
            # of rules that survived. They are separate fields because they are
            # separate facts: matched-but-chose-nobody is an ambiguity, matched-
            # but-wrong-shape is not, and `recall_set` is the union of both with
            # `applicable_rules`.
            detail = exp.get("decision_detail") or {}
            for field, why_it_lost in (
                    ("rules_without_a_unique_candidate",
                     "had no unique candidate, so it had no surviving application"),
                    ("rules_excluded_by_cardinality",
                     "was excluded by its own cardinality guard")):
                for rid in (detail.get(field) or []):
                    check(rid in rules,
                          f"{where}: unknown rule {rid!r} in decision_detail.{field}")
                    check(rid not in app,
                          f"{where}: {rid} {why_it_lost} and must not be in "
                          "applicable_rules")
                    # A CLAIMED CARDINALITY EXCLUSION MUST BE TRUE. Absence from
                    # `applicable_rules` was the only requirement, so a rule whose
                    # guard the shape satisfies could be recorded as excluded by it
                    # - a 1:1 rule listed against a 1:1 shape passed. The arithmetic
                    # lived only in `case_obligations`, which reaches one fixture.
                    if field == "rules_excluded_by_cardinality" and rid in rules:
                        card = rules[rid].get("cardinality") or {}
                        nf, nt = len(frm), len(to)
                        blocked = (card.get("min_successors", 0) > nt
                                   or card.get("min_predecessors", 0) > nf)
                        check(blocked,
                              f"{where}: {rid} is recorded as excluded by cardinality, "
                              f"but {card} does not rule out a {nf}:{nt} shape. The "
                              "guard has to do the excluding, not the record of it.")
            # `conflicting_rules` is the third recorded stage and was checked
            # nowhere: a conflict fixture could omit it, or name unrelated ids, and
            # still pass its outcome, reason and arbitration checks.
            conflicting_ids = detail.get("conflicting_rules")
            refused = (outcome == "unresolved" and app)
            if refused:
                check(conflicting_ids is not None,
                      f"{where}: rules applied and the answer is a refusal, so the "
                      "disagreement must be recorded in decision_detail.conflicting_rules")
                check(set(conflicting_ids or []) == set(app),
                      f"{where}: conflicting_rules {sorted(conflicting_ids or [])} is not "
                      f"the set that disagreed, {sorted(app)}. The record is what a later "
                      "reader uses to decide whether a seventh outcome is needed.")
            else:
                check(conflicting_ids is None,
                      f"{where}: decision_detail.conflicting_rules is set, but nothing "
                      "was refused for disagreeing here")

            overlap = (set(detail.get("rules_without_a_unique_candidate") or [])
                       & set(detail.get("rules_excluded_by_cardinality") or []))
            check(not overlap,
                  f"{where}: {sorted(overlap)} recorded as BOTH unable to choose and "
                  "excluded by cardinality. A rule lost at one stage, and the two "
                  "answer different questions when the rule is later changed.")

            for kind, defeater in (exp.get("boundary_defeated") or {}).items():
                spec = next((s for s in senior["boundary_evidence_kinds"].values()
                             if s["value"] == kind), None)
                check(spec is not None, f"{where}: unknown boundary kind {kind!r}")
                if spec is None:
                    continue
                check(defeater in [d.strip() for d in spec["defeated_by"].split(",")],
                      f"{where}: {kind!r} is not defeated by {defeater!r} in the senior "
                      f"contract, which lists {spec['defeated_by']!r}")
                check(bool(collect(rev_b, defeater)),
                      f"{where}: claims {kind!r} is defeated by {defeater}, which is empty")
                # FOLLOW THE DECLARED ROLE. This used to take `frm[0]` and fall
                # back to `to[0]`, computing `role` and then ignoring it - so a
                # `successor.*` boundary was checked against the PREDECESSOR, and a
                # fixture could defeat a boundary that never applied to the side it
                # names. Every occurrence on the declared side is checked, not the
                # first one.
                role, attr = spec["match"].split(".")
                subjects = frm if role == "predecessor" else to
                check(bool(subjects),
                      f"{where}: {kind!r} matches on {spec['match']}, and this "
                      f"expectation names no {role}. There is nothing for the boundary "
                      "to have applied to, so defeating it proves nothing.")
                observed = collect(rev_b, spec["observable_from"])
                for oid in subjects:
                    wanted = by_id.get(oid, {}).get(attr)
                    check(wanted in observed,
                          f"{where}: {kind!r} would not have applied to {oid} anyway - "
                          f"{spec['observable_from']} holds {sorted(observed)!r}, which "
                          f"does not name its {attr} {wanted!r}, so defeating it proves "
                          "nothing")

        # ---- the case's PREREGISTERED OBLIGATION, not just its answer. -------
        # A case can reach the right outcome for the wrong reason: move the losing
        # rule out of `applicable_rules` and the copy case still reports `branched`
        # while showing dominance doing nothing. The suite cannot notice on its own
        # - which rules really fired is applicability - so the obligation is
        # declared in the contract and checked against the fixture's declarations.
        duties = obligations.get(name)
        check(duties is not None,
              f"{name}: no entry in `case_obligations`; nothing says what this case "
              "must exhibit beyond being green")
        for duty in duties or []:
            check(duty in obligation_meanings, f"{name}: unknown obligation {duty!r}")
            met = False
            for exp in case.get("expect", []):
                app_s = set(exp.get("applicable_rules") or [])
                lic_s = set(exp.get("licensed_by") or [])
                if duty == "dominance_did_work":
                    met |= any((w, r) in edges for r in app_s - lic_s for w in lic_s)
                elif duty == "defeat_removed_a_signal":
                    met |= bool(exp.get("signals_defeated"))
                elif duty == "input_was_unavailable":
                    met |= bool(exp.get("inputs_unavailable"))
                elif duty == "blunt_rule_recorded":
                    met |= bool((exp.get("decision_detail") or {})
                                .get("rules_without_a_unique_candidate"))
                elif duty == "refusal_was_recorded":
                    dd = exp.get("decision_detail") or {}
                    for pair in refusals:
                        if pair <= app_s:
                            check(set(dd.get("conflicting_rules") or []) == set(app_s),
                                  f"{name}: exercises the declared refusal "
                                  f"{sorted(pair)} but records "
                                  f"{sorted(dd.get('conflicting_rules') or [])}")
                            check(not lic_s,
                                  f"{name}: a refused conflict licenses nothing, got "
                                  f"{sorted(lic_s)}")
                            met = True
                elif duty == "cardinality_excluded_a_rule":
                    excluded = ((exp.get("decision_detail") or {})
                                .get("rules_excluded_by_cardinality") or [])
                    for rid in excluded:
                        check(rid in rules, f"{name}: unknown rule {rid!r} in "
                                            "excluded_by_cardinality")
                        check(rid not in app_s,
                              f"{name}: {rid} is excluded by cardinality and also "
                              "applicable")
                        card = rules.get(rid, {}).get("cardinality", {})
                        nf, nt = len(as_list(exp.get("frm"))), len(as_list(exp.get("to")))
                        blocked = (card.get("min_successors", 0) > nt
                                   or card.get("min_predecessors", 0) > nf)
                        check(blocked,
                              f"{name}: {rid} is claimed excluded by cardinality, but "
                              f"{card} does not rule out a {nf}:{nt} shape. The guard has "
                              "to do the excluding, not the note.")
                        met = True
            check(met, f"{name}: preregistered to exhibit {duty!r}, and no expectation "
                       f"does. {obligation_meanings.get(duty, '')}")

        check(claimed_a == occ_a,
              f"{name}: revision A occurrences unaccounted for: {sorted(occ_a - claimed_a)}")
        check(claimed_b == occ_b,
              f"{name}: revision B occurrences unaccounted for: {sorted(occ_b - claimed_b)}")

        seen_forbid: set[str] = set()
        for forbidden in case.get("forbid", []):
            check(isinstance(forbidden, str) and len(forbidden) > 5,
                  f"{name}: empty or stub entry in `forbid`")
            check(forbidden not in seen_forbid,
                  f"{name}: `forbid` repeats an entry verbatim: {forbidden[:60]!r}")
            seen_forbid.add(forbidden)
        check(bool(seen_forbid), f"{name}: `forbid` is empty - the case rules nothing out")

    # Every outcome a RULE can license must be licensed by some case, or it is
    # frozen in name only and a mapper may reach it however it likes. This is the
    # analogue of step 0's outcome sweep; it is not a demand for one happy-path
    # case per rule, because this matrix is about shapes where two answers are
    # available and a rename that simply works is not one. R-CONT-RENAME is
    # constrained by the senior corpus, where `rename-with-context-continues` is
    # the only rule that licenses it.
    # A declared refusal with no case is a decision nothing pins - the defect this
    # project keeps finding in its own drafts. The N:M pair was frozen in the
    # contract and exercised by no fixture at all until this check was written.
    for pair in sorted(({frozenset(c["between"]) for c in
                         policy["deliberately_unresolved_conflicts"]}), key=sorted):
        check(pair in exercised_refusals,
              f"the declared refusal {sorted(pair)} is exercised by no preregistered "
              "case. A conflict the contract deliberately refuses is a decision, and a "
              "decision with no case is frozen in name only.")

    for wanted in sorted({rules[r]["outcome"] for r in ids} | {"unresolved"}):
        check(wanted in licensed_outcomes,
              f"no preregistered case reaches {wanted!r}; the policy can license it and "
              "nothing pins how")

    # ---- 4c. THE DOC AND THE CONTRACT AGREE. --------------------------------
    # Same gate step 0 uses. A document that stops naming a case, or keeps saying
    # a mapper exists when one does not, is worse than no document: it is a
    # confident description of something else.
    with open(DOC, encoding="utf-8") as fh:
        doc = fh.read()
    check("finding-lineage-decision/v1" in doc, "the doc must name the contract it freezes")
    check("implementation not started" in doc,
          "the doc must keep saying no mapper exists, until one does")
    for case_name in preregistered:
        check(case_name in doc, f"the doc does not mention preregistered case {case_name!r}")
    for rid in ids:
        check(rid in doc, f"the doc does not mention rule {rid!r}")
    for reason in sorted(emitted):
        tail = reason.rsplit(":", 1)[-1]
        check(tail in doc, f"the doc does not mention the reason {tail!r} the policy emits")
    # ...and the section that calls itself exhaustive must actually be. Token
    # presence anywhere in the file is too weak: the refusal table went stale
    # while staying green, because `insufficient-evidence-kind` happened to appear
    # in a different section a hundred lines earlier.
    table = doc.partition("### Every refusal this policy can emit")[2].partition("\n## ")[0]
    check(bool(table), "the doc must carry a section listing every refusal the policy emits")
    listed = set(re.findall(r"^\| `([a-z-]+)` \|", table, re.M))
    want = {r.rsplit(":", 1)[-1] for r in emitted}
    check(listed == want,
          "the refusal table and the policy disagree.\n"
          f"  table lists: {sorted(listed)}\n"
          f"  policy emits: {sorted(want)}\n"
          "  A section that calls itself exhaustive has to be, or a reader "
          "implementing from it misses a branch that exists.")

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
        for (x, y), state in zip(model_pairs, combo, strict=True):
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
          f"different-outcome pairs all classified, {len(results)} subsets total, "
          f"{len(preregistered)} preregistered cases (totality is a theorem of "
          "completeness and acyclicity, swept anyway; mapper not implemented)")
    return 0


def test_lineage_decision() -> None:
    """Pytest entry point; the bare-script path uses `main()` directly."""
    rc = main()
    if rc != 0:
        raise AssertionError(f"lineage decision policy failed: {len(fails)} check(s)")


if __name__ == "__main__":
    raise SystemExit(main())
