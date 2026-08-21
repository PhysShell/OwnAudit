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

# The record field for unevaluable signals, read from the contract that DECLARES
# it rather than repeated here. `unavailable_inputs.recorded_as` used to be prose
# and this name was a literal at three call sites, so the two could drift apart
# with nothing to object - the contract could point a mapper at `signals_defeated`
# and every check stayed green. Now there is one source and it is the contract's.
UNAVAILABLE_FIELD = (json.load(open(POLICY, encoding="utf-8"))
                     ["unavailable_inputs"]["recorded_as"])
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


class _Marked(dict):
    """A parsed JSON object that remembers the keys declared twice inside it.

    `json.load` keeps the last of a duplicated key and drops the other without a
    word, so the duplication has to be caught during the raw parse. A plain dict
    cannot carry that fact to a later walk; this can."""
    __slots__ = ("duplicate_keys",)


def duplicate_json_keys(path: str) -> list:
    """Dotted paths to keys declared twice in ONE object, from the RAW parse.

    Two earlier versions of this function got its own description wrong, in
    opposite directions. The first promised dotted paths and returned bare names.
    The second returned the key plus its siblings and asserted that a path was not
    obtainable, because `object_pairs_hook` is called innermost-first and never
    learns where it is. That second claim was false: the hook does not know, but a
    walk from the root afterwards does, once each object carries what it saw. So
    the paths are real - `arbitration.conflict.reason`, not `reason` - and the
    docstring finally matches the code.

    Stating something impossible when it is merely inconvenient is the same defect
    this suite keeps finding elsewhere: a description that claims more, or less,
    than the code does."""
    def hook(pairs):
        obj = _Marked(pairs)
        seen, dups = set(), []
        for key, _ in pairs:
            if key in seen:
                dups.append(key)
            seen.add(key)
        obj.duplicate_keys = dups
        return obj

    with open(path, encoding="utf-8") as fh:
        root = json.load(fh, object_pairs_hook=hook)

    found: list = []

    def walk(node, trail):
        if isinstance(node, _Marked):
            for key in node.duplicate_keys:
                found.append(".".join(trail + [key]) or key)
            for key, value in node.items():
                walk(value, trail + [key])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, trail + [f"[{i}]"])

    walk(root, [])
    return sorted(set(found))


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
    unavailable = as_list(exp.get(UNAVAILABLE_FIELD))
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


def record_names(entry: dict, key: str, wanted) -> bool:
    """One record entry naming one occurrence, on one key. A fold's `from` is a
    LIST of symbols and a copy's is a single path; `entry_shape` says which, so
    membership and equality are the same question asked of two shapes."""
    if not isinstance(entry, dict) or key not in entry:
        return False
    val = entry[key]
    return wanted in val if isinstance(val, list) else wanted == val


def related_by(entry: dict, pairs: list, preds, succs, by_id: dict) -> set:
    """The (predecessor, successor) pairs ONE record entry relates.

    Conjunctive across the keys the catalog matches on: a record relates a pair
    or it relates nothing. Collecting the keys separately and intersecting later
    accepts `Doc.cs -> Unrelated.cs` beside `Other.cs -> DocCopy.cs` as though
    one record connected the two."""
    out = set()
    for p in preds:
        for t in succs:
            subject = {"predecessor": p, "successor": t}
            if all(record_names(entry, key, by_id.get(subject[role], {}).get(at))
                   for key, role, at in pairs):
                out.add((p, t))
    return out


def catalog_read(cat_spec: dict, rev_b: dict) -> tuple:
    """(field path, entries, match keys) for one structural signal."""
    field = str(cat_spec.get("observable_from", "")).split("[].")[0]
    entries = (rev_b.get(field.partition(".")[2]) or []
               if field.startswith("revision_b.") else [])
    # `signal_bindings` yields the full dotted READ PATH, not the bare entry key
    # - `revision_b.copies[].from`, not `from`.
    pairs = [(read.split("[].")[-1], role, at)
             for read, role, at in signal_bindings(cat_spec)]
    return field, entries, pairs


def raw_dominance_edges(policy: dict) -> list:
    """Occurrences, NOT a set. `classified exactly once` is a claim about the
    declarations, and a set answers a weaker question - it would let
    `loses: ["R-X", "R-X"]` collapse into one edge and pass."""
    return [(p["winner"], loser)
            for p in policy["dominance"]["declared_pairs"]
            for loser in p["loses"]]


def refusal_shape_failures(policy: dict) -> list:
    """Complaints about the RAW `between` lists, before any frozenset sees them.

    `frozenset(["R-A", "R-B", "R-A"])` is a valid two-rule pair, so a declaration
    with three members passed every downstream check while a mapper reading the
    contract directly saw something else. The same reason `raw_dominance_edges`
    keeps occurrences rather than a set: the claim is about the DECLARATION."""
    out = []
    for entry in policy["deliberately_unresolved_conflicts"]:
        raw = entry.get("between")
        if not isinstance(raw, list):
            out.append(f"a declared refusal has `between` = {raw!r}, not a list")
            continue
        if len(raw) != 2:
            out.append(f"the declared refusal {raw!r} names {len(raw)} rules; a "
                       "refusal is a PAIR, and the frozenset below would silently "
                       "make one out of any repetition")
        rep = sorted({r for r in raw if raw.count(r) > 1})
        if rep:
            out.append(f"the declared refusal {raw!r} repeats {rep!r}; a rule cannot "
                       "conflict with itself, and the repetition disappears the "
                       "moment this becomes a set")
    return out


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
    for msg in refusal_shape_failures(policy):
        check(False, msg)
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

    # ...and the same branches' OUTCOME, which that rule left loose one field over.
    # `all_agree` says "the shared outcome" because the value is COMPUTED from the
    # survivors; replacing it with a literal `continued` turned the general law
    # into a specific claim the algebra contradicts, and nothing objected. The
    # refusing branches are the mirror: `arbitrate` hard-codes `unresolved` for
    # every one of them, so a literal there must be that literal.
    senior_outcomes = set(senior["outcomes"])
    agree = policy["arbitration"]["all_agree"]

    # EVERY node under `arbitration` that carries an outcome, not the three the
    # reason loop happens to visit. Writing this as a list of branches is what
    # left `all_agree` loose in the first place; a first attempt at this check
    # then added an `outcome` to the multiplicity CONTAINER, which the branch list
    # does not visit either - a declaration nobody reads, introduced while fixing
    # declarations nobody reads. So it walks.
    def arbitration_nodes(node, trail):
        if isinstance(node, dict):
            if "outcome" in node:
                yield ".".join(trail), node
            for k, v in node.items():
                yield from arbitration_nodes(v, trail + [k])
    # ENUMERATE THE LEAVES, not the nodes that happen to carry the field being
    # checked. `arbitration_nodes` yields only nodes that already have `outcome`,
    # so DELETING `none_applies.outcome` removed that leaf from the checks
    # entirely and left a refusal branch with no declared result. A validator
    # keyed on the presence of what it validates cannot see an absence.
    def arbitration_leaves(node, trail):
        if isinstance(node, dict):
            if "reason" in node or "implements" in node:
                yield ".".join(trail), node
            for k, v in node.items():
                yield from arbitration_leaves(v, trail + [k])
    for path_a, node in arbitration_leaves(policy["arbitration"], ["arbitration"]):
        check("outcome" in node,
              f"{path_a} names a reason and implements a `reason_mapping` entry, so it "
              "is a decision, but declares no `outcome`. A mapper reading it learns "
              "what to call the refusal and not that it IS one.")

    for path_a, node in arbitration_nodes(policy["arbitration"], ["arbitration"]):
        if node is agree:
            continue
        got = node.get("outcome")
        # A DECISION LEAF, not a container. `multiplicity` holds two branches that
        # reach DIFFERENT answers - one is `branched` or `merged` per the
        # structural rules, the other refuses - so an outcome on the parent
        # contradicts a child whatever it says. The first version of this check
        # accepted `unresolved` there because it treated every non-`all_agree`
        # node carrying an outcome as a refusal.
        check("reason" in node or "implements" in node,
              f"{path_a} declares outcome {got!r} but names no reason and implements "
              "no `reason_mapping` entry, so it is a container rather than a decision. "
              "Its children reach the outcomes; a parent claiming one contradicts "
              "whichever child disagrees.")
        check(got == "unresolved",
              f"{path_a} declares outcome {got!r}. Every arbitration branch that is "
              "not `all_agree` refuses, and `arbitrate` answers `unresolved` on all of "
              "them, so any other value is a claim the algebra contradicts.")

    check("implements" not in agree,
          "`arbitration.all_agree` is not a refusal and must not implement a "
          "`reason_mapping` entry; the record it produces carries no reason at all.")
    # A MARKER, not merely a non-literal. This asked only that the value was none
    # of the six senior outcomes, so deleting the field or writing `no outcome`
    # passed - and the field exists precisely to tell a mapper the value is
    # computed. `not in senior_outcomes` is the check claiming more than it
    # checks, one more time.
    agree_out = agree.get("outcome")
    check(isinstance(agree_out, dict),
          f"`arbitration.all_agree.outcome` is {agree_out!r}. It must be a machine-"
          "readable marker saying the value is COMPUTED; a prose string cannot be "
          "distinguished from a missing field or from a wrong one.")
    if isinstance(agree_out, dict):
        check(agree_out.get("computed_from") == "surviving_rules"
              and agree_out.get("field") == "outcome",
              f"`arbitration.all_agree.outcome` marks {agree_out.get('computed_from')!r}"
              f".{agree_out.get('field')!r}; the outcome is the `outcome` shared by the "
              "SURVIVING rules, which is what `licensed_by_rule` and `arbitrate` both "
              "implement.")

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

            # IF AND ONLY IF, for the minima too. Each was required where the
            # shape needs it and forbidden nowhere, so a 1:1 rule could carry
            # `min_successors` and a 1:N rule `min_predecessors`. Not inert: the
            # `cardinality_excluded_a_rule` obligation reads exactly these fields
            # to decide whether a rule is GENUINELY unable to fit a shape, so a
            # spurious minimum makes that obligation satisfiable for a rule
            # nothing excluded.
            for field, needed_by in (("min_successors", "1:N"),
                                     ("min_predecessors", "N:1")):
                check((field in card) == (shape == needed_by),
                      f"{rid} is {shape!r} and {'declares' if field in card else 'omits'} "
                      f"`{field}`, which belongs to {needed_by!r} and only there. A "
                      "minimum on the side a shape has exactly one of describes nothing, "
                      "and the cardinality-exclusion obligation still reads it.")

        # A rule whose cardinality is not 1:1 says something about a GROUP, so it
        # must also say what each partner shows on its own. `a rule of outcome
        # continued` used to stand here and was unsatisfiable on the very frozen
        # cases these rules exist for - see `rules_note`.
        prof = rules[rid].get("partner_profile")
        if isinstance(card, dict):
            # IF AND ONLY IF. This required a profile of group rules and forbade
            # one nowhere, so a 1:1 rule could declare `partner_profile` - which
            # names the REPEATED side, of which it has none - and `rule_needs`
            # would silently fold those kinds into its requirements. The sibling
            # `record_binding` check was written biconditional; this one was not,
            # and the two sat four lines apart.
            check(isinstance(prof, dict) == (card.get("shape") != "1:1"),
                  f"{rid} is {card.get('shape')!r} and "
                  f"{'declares' if prof is not None else 'omits'} a `partner_profile`. "
                  "A profile says what each partner in a GROUP shows on its own; a 1:1 "
                  "rule has no group, and a group rule that omits one licenses partners "
                  "nothing was asked of.")
        if prof is not None:
            check(isinstance(prof, dict) and prof.get("per") in ("successor", "predecessor"),
                  f"{rid}: partner_profile must say which side it is `per`")
            # ...and it must be the REPEATED side. `per` accepted either value for
            # either shape, so a 1:N rule could profile the predecessor - the one
            # occurrence there is exactly one of - and license a branch whose
            # successors show none of the required evidence. The senior contract
            # defines `branched` as several EQUALLY SUPPORTED successors, and a
            # profile aimed at the singleton side supports none of them.
            #
            # The repeated side is read off the shape, not chosen: `1:N` means one
            # predecessor and N successors. There is no policy here to hold an
            # opinion about, unlike the quantifier, which is why this one is
            # derived where that one is declared.
            repeated = {"1:N": "successor", "N:1": "predecessor"}.get(
                (rules[rid].get("cardinality") or {}).get("shape"))
            if repeated:
                check(prof.get("per") == repeated,
                      f"{rid} is {(rules[rid].get('cardinality') or {}).get('shape')!r}, so "
                      f"the group is its {repeated}s, but `partner_profile.per` is "
                      f"{prof.get('per')!r} - the side there is exactly one of. A profile "
                      "checked against the singleton says nothing about the partners the "
                      "outcome rests on.")
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
        # NO RULE MAY REQUIRE AN IMPOSSIBLE COMBINATION. The senior contract
        # freezes which kinds cannot co-occur; a rule demanding both is dead and
        # takes its outcome down quietly with it. This is one of the two things
        # standing in for a binding of `requires_all` to evidence, which the
        # suite cannot do without becoming a second mapper - see the note on
        # `rule_coverage_rule`.
        needs = rule_needs(rules[rid])
        for excl in senior.get("mutually_exclusive_evidence_kinds") or []:
            pair = set(excl.get("between") or [])
            check(not pair <= needs,
                  f"{rid} requires {sorted(pair)} together, which "
                  "`finding-lineage/v1` freezes as mutually exclusive. No evidence "
                  "can satisfy the rule, so it licenses nothing and its outcome "
                  "silently degrades to `unresolved`.")

        # The abandoned wording must not creep back in under its old names.
        for dead in ("requires_per_successor", "requires_per_predecessor"):
            check(dead not in rules[rid],
                  f"{rid} still carries {dead!r}. That condition was falsified against the "
                  "frozen corpus: every continued rule needs `structural_context`, and the "
                  "copy and fold cases change the enclosing symbol.")

    # TWO RULES MAY NOT BE THE SAME RULE. Identical requirements under one
    # outcome make a pair indistinguishable: no evidence can satisfy either
    # without satisfying both, so one of them licenses nothing that the other
    # does not, and retiring it would change no mapping. The pair is also
    # invisible to arbitration, which only ever sees rules AGREEING.
    #
    # This is the second stand-in for binding `requires_all` to evidence. It is
    # what catches a rename rule whose `path_rename` is swapped for `same_path`:
    # the result is R-CONT-SAME-SITE under a second name.
    by_requirements: dict = {}
    for rid in ids:
        key = (outcomes[rid], frozenset(rule_needs(rules[rid])),
               rules[rid].get("cardinality", {}).get("shape"))
        by_requirements.setdefault(key, []).append(rid)
    for key, group in sorted(by_requirements.items(), key=lambda kv: sorted(kv[1])):
        check(len(group) == 1,
              f"{sorted(group)} license {key[0]!r} at {key[2]!r} on identical "
              f"requirements {sorted(key[1])}. They are one rule under two names: "
              "nothing can satisfy either without satisfying both, so neither can "
              "be cited for a mapping the other does not equally license.")

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
                  f"the {label} declares {dup!r} twice. `json.load` keeps the last one "
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
    # NO TYPE FILTER. This read the whole object and kept the string values, to
    # skip the prose sibling - so a mapping whose target was `null`, a list or an
    # object vanished BEFORE validation and resolved to `catalog.get(None)`,
    # leaving the rule licensed and its record unchecked. The mappings now live
    # under `map` and the prose does not, so there is nothing to classify and
    # every entry is validated.
    kind_records = (policy.get("evidence_kind_records") or {}).get("map") or {}
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

    # THE CATALOG'S READ PATHS, FOR EVERY SIGNAL. These were checked only for the
    # two signals that happen to be DEFEATERS, because the defeat loop was the
    # only thing that ever called `signal_bindings`. `copy_record` and
    # `merge_record` - the two carrying `branched` and `merged` - could name a
    # revision field nothing has, or match on an occurrence attribute that does
    # not exist, with the suite green. `observable_from` is the contract telling a
    # mapper WHERE to read; pointed at nothing, every structural rule stops
    # applying and the policy degrades to `unresolved` in silence.
    #
    # `finding-lineage/v1` binds its own `observable_from` this way already, so
    # the junior catalog was simply the looser of the two.
    occurrence_attrs = {"path", "enclosing_symbol", "pattern_id",
                        "anchored_content", "start_line", "start_column",
                        "occurrence_id"}
    for signal, cat_spec in sorted(policy["structural_signals"].items()):
        where_s = f"structural_signals.{signal}"
        read_from = str(cat_spec.get("observable_from", ""))
        check(read_from.startswith("revision_b."),
              f"{where_s}.observable_from must name a revision B field, got "
              f"{read_from!r}")
        matches = cat_spec.get("matches")
        check(isinstance(matches, dict) and matches,
              f"{where_s} declares no `matches`, so nothing says which occurrence "
              "the record is about and any record in revision B would do")
        for key, subject in (matches or {}).items():
            role, dot, attr = str(subject).partition(".")
            check(role in ("predecessor", "successor"),
                  f"{where_s}.matches[{key!r}] names role {role!r}; a record relates "
                  "predecessors to successors and nothing else")
            check(bool(dot) and attr in occurrence_attrs,
                  f"{where_s}.matches[{key!r}] compares {subject!r}, and {attr!r} is "
                  f"not an occurrence attribute. Known: {sorted(occurrence_attrs)}")
        shape = cat_spec.get("entry_shape")
        if isinstance(shape, dict):
            check(set(matches or {}) <= set(shape),
                  f"{where_s}.matches names {sorted(set(matches or {}) - set(shape))}, "
                  "which `entry_shape` does not declare")

    # THE KIND -> RECORD MAP MUST NAME A REAL RECORD. Resolution ends in
    # `catalog.get(sig)`, and a miss there reads as "this requirement has no
    # structural record", which is the correct answer for `same_path` and the
    # wrong one for a mapping that points at nothing. Repointing `path_rename` at
    # `missing_rename_record` left R-CONT-RENAME licensed and its record
    # unchecked - fail-open, in the resolution step added to close a fail-open.
    senior_kinds = set(senior["evidence_kinds"])
    check(isinstance(kind_records, dict) and bool(kind_records),
          "`evidence_kind_records.map` must carry the kind -> record mappings; an "
          "empty or missing map silently unbinds every rule naming a senior kind")
    # TOTAL OVER WHAT RULES REQUIRE DIRECTLY. Validating each entry proves only
    # that the entries present are well-formed; the map could be replaced with a
    # valid mapping nobody consumes - `same_pattern_id`, reached only through a
    # partner profile - and `path_rename` then resolved to nothing while every
    # per-entry check passed. Domain equality is the fail-closed form.
    # TOTAL OVER THE SENIOR VOCABULARY, not over this map's domain. The loop
    # below visits only kinds the map carries, and the map deliberately excludes
    # partner-profile-only kinds - so removing `same_pattern_id` from the frozen
    # observation left it unclassified with everything green. That is the same
    # valid-but-not-total defect this map was just fixed for, one layer up, in the
    # section added to fix it.
    observation = {k: v for k, v in
                   (senior.get("evidence_kind_observation") or {}).items()
                   if isinstance(v, str)}
    check(set(observation) == set(senior["evidence_kinds"]),
          "`finding-lineage/v1.evidence_kind_observation` must classify EVERY evidence "
          f"kind. Missing {sorted(set(senior['evidence_kinds']) - set(observation))}, "
          f"unexpected {sorted(set(observation) - set(senior['evidence_kinds']))}. A "
          "kind left unclassified is one a partner profile would have to guess about, "
          "which is the fact this section exists to settle.")
    # ...and the VALUES, here rather than only where the junior map consumes them.
    # Totality alone accepted `same_pattern_id: "sometimes"`: a string, so it
    # survived the filter and counted toward the key set, and its value was
    # checked nowhere because that kind is reached only through a partner profile
    # and so is deliberately outside the map's domain. Present-and-total is not
    # the same as meaningful, which is this family of defect one notch over.
    OBSERVATION_CLASSES = ("pair_property", "revision_record")
    for kind, how in sorted(observation.items()):
        check(how in OBSERVATION_CLASSES,
              f"`evidence_kind_observation[{kind!r}]` is {how!r}, which is not one of "
              f"{list(OBSERVATION_CLASSES)}. An unrecognised class says a kind was "
              "classified without saying how it is observed, and every consumer must "
              "then guess exactly what this section exists to settle.")

    NO_RECORD = "no_structural_record"
    direct = {k for r in rules.values() for k in (r.get("requires_all") or [])}
    want_domain = {k for k in direct if k in senior_kinds}
    check(set(kind_records) == want_domain,
          "`evidence_kind_records.map` must name exactly the senior evidence kinds "
          f"some rule requires DIRECTLY. Missing {sorted(want_domain - set(kind_records))}, "
          f"unexpected {sorted(set(kind_records) - want_domain)}. A missing kind "
          "resolves to no record and skips its binding; an extra one is a mapping "
          "nothing consumes, which is how this map was first made to unbind a rule.")
    for kind, sig_name in sorted(kind_records.items()):
        check(isinstance(sig_name, str),
              f"`evidence_kind_records.map[{kind!r}]` is {sig_name!r}. A non-string "
              "target resolves to no record and skips the binding, which is the "
              "fail-open this map exists to close.")
        # The escape hatch cannot be aimed at a kind a record DOES witness.
        # `path_rename: no_structural_record` unbound the rename rule and stayed
        # green: an explicit "nothing observes this" is only honest for kinds
        # `finding-lineage/v1` classifies as pair properties.
        observed_as = observation.get(kind)
        check((sig_name == NO_RECORD) == (observed_as == "pair_property"),
              f"`evidence_kind_records.map[{kind!r}]` is {sig_name!r} while the senior "
              f"contract observes that kind as a {observed_as!r}. A "
              f"{'pair property takes ' + NO_RECORD if observed_as == 'pair_property' else 'revision record takes a signal name'}"
              ", and the other way round either invents a record or unbinds a real one.")
        if sig_name == NO_RECORD:
            continue
        check(kind in senior_kinds,
              f"`evidence_kind_records` maps {kind!r}, which `finding-lineage/v1` does "
              "not carry as an evidence kind. The map exists to say where a SENIOR "
              "kind is observed; a key that is not one binds nothing.")
        check(kind not in policy["structural_signals"],
              f"`evidence_kind_records` maps {kind!r}, which is already a structural "
              "signal. It would then resolve two ways, and the two could disagree.")
        check(sig_name in policy["structural_signals"],
              f"`evidence_kind_records` maps {kind!r} to {sig_name!r}, which is neither "
              f"a structural signal nor {NO_RECORD!r}. Resolution would find no record and "
              "silently skip the binding, which is exactly what the map was added to "
              "prevent.")

    # ...and the group quantifier, which used to live in `requires_all_scope` as
    # prose. A 1:1 rule could claim GROUP scope and a group rule could drop the
    # declaration entirely, both silently.
    vocab = policy["record_binding_vocabulary"]
    for rid in sorted(rules):
        rule_ = rules[rid]
        check("requires_all_scope" not in rule_,
              f"{rid} still carries `requires_all_scope`. It was prose nothing read, "
              "and `record_binding` replaced it; keeping both is two authorities for "
              "one fact, which is how this contract has gone wrong before.")
        binding = rule_.get("record_binding")
        is_group = (rule_.get("cardinality") or {}).get("shape") != "1:1"
        check(bool(binding) == is_group,
              f"{rid}: `record_binding` is declared for group rules and only for them; "
              f"shape is {(rule_.get('cardinality') or {}).get('shape')!r} and the "
              f"binding is {'present' if binding else 'absent'}. A 1:1 rule with one "
              "points a mapper at a partner set that does not exist.")
        if not binding:
            continue
        structural = [k for k in rule_.get("requires_all") or []
                      if k in policy["structural_signals"]]
        check(len(structural) == 1,
              f"{rid} is a group rule requiring {structural!r} structural signals; "
              "the binding is about exactly one record")
        for sig in structural:
            roles = {r for _, r, _ in signal_bindings(policy["structural_signals"][sig])}
            declared = {k for k in binding if k in ("predecessor", "successor")}
            check(declared == roles,
                  f"{rid}.record_binding names roles {sorted(declared)} but {sig} "
                  f"matches on {sorted(roles)}. The roles are the catalog's, not a "
                  "second opinion about which side the group is on.")
        for role in ("predecessor", "successor"):
            spec_r = binding.get(role)
            if not isinstance(spec_r, dict):
                continue
            check(spec_r.get("quantifier") in vocab["quantifier"],
                  f"{rid}.record_binding.{role} uses quantifier "
                  f"{spec_r.get('quantifier')!r}, which the vocabulary does not carry")
            if "excluding" in spec_r:
                check(spec_r["excluding"] in vocab["excluding"],
                      f"{rid}.record_binding.{role} excludes {spec_r['excluding']!r}, "
                      "which the vocabulary does not carry. Unknown tokens are "
                      "rejected, not ignored.")

    senior_limitations_set = set(senior["limitations"].values())
    unavailable_from = str(policy["unavailable_inputs"].get("observable_from", ""))
    check(unavailable_from.startswith("revision_b."),
          "`unavailable_inputs.observable_from` must name a revision B field, got "
          f"{unavailable_from!r}")
    check(UNAVAILABLE_FIELD in policy["record_additions"],
          f"`unavailable_inputs.recorded_as` names {UNAVAILABLE_FIELD!r}, which is not a "
          "field `record_additions` declares. The suite reads the record through this "
          "name, so an undeclared one silently reads nothing.")
    check(UNAVAILABLE_FIELD != "signals_defeated",
          "`unavailable_inputs.recorded_as` points at the field for signals that were "
          "evaluated and removed. `distinct_from` in this very section says why those "
          "are not the same thing: one was never readable, the other was read and did "
          "not hold.")
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
    licensed_rules: set[str] = set()
    exercised_refusals: set = set()
    exercised_reasons: set = set()
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
        # BEFORE THE SETS. `{o["occurrence_id"] for o in ...}` silently collapses
        # a repeated id, and so does `by_id`; the raw LIST length then still
        # satisfied a 1:N minimum, so `to: ["occ-b1", "occ-b1"]` froze a branch
        # with one distinct successor. An occurrence id is an identity, and two
        # records sharing one is malformed input rather than a duplicate.
        for side, rev in (("A", rev_a), ("B", rev_b)):
            raw_ids = [o.get("occurrence_id") for o in rev.get("occurrences", [])]
            dupes = sorted({i for i in raw_ids if raw_ids.count(i) > 1})
            check(not dupes,
                  f"{name}: revision {side} declares {dupes!r} more than once. An "
                  "occurrence id is an identity; the sets below would silently keep "
                  "one and drop the other.")
        occ_a = {o["occurrence_id"] for o in rev_a.get("occurrences", [])}
        occ_b = {o["occurrence_id"] for o in rev_b.get("occurrences", [])}
        # ACROSS the revisions too. Per-revision duplicate checks see nothing
        # wrong when A and B each declare `occ-a1` once, and the combined `by_id`
        # then lets the B record overwrite the A record - preregistering a
        # self-edge, and making the structural binding read a successor's
        # attributes while believing they are a predecessor's. An occurrence id
        # cannot span runs at all; `finding-lineage/v1` says so.
        shared = sorted(occ_a & occ_b)
        check(not shared,
              f"{name}: {shared!r} appears in BOTH revisions. An occurrence id names "
              "one occurrence in one run, so a shared id is two different occurrences "
              "under one name - and `by_id` keeps only the second.")
        by_id = {o["occurrence_id"]: o for o in
                 rev_a.get("occurrences", []) + rev_b.get("occurrences", [])}
        # COUNTED, not collected. `update` proves an occurrence is claimed at
        # least once and forgets which expectation claimed it, so a second,
        # separately well-formed expectation over the same occurrences was
        # accepted - preregistering `branched` and `continued` for one predecessor
        # at once. The matrix is a set of decisions about a corpus; two decisions
        # about one occurrence is a contradiction frozen into a fixture.
        claim_a: dict = {}
        claim_b: dict = {}
        claimed_a, claimed_b = set(), set()

        for i, exp in enumerate(case.get("expect", [])):
            where = f"{name}[{i}]"
            outcome = exp.get("outcome")
            check(outcome in senior_outcomes,
                  f"{where}: outcome {outcome!r} is not in the frozen vocabulary")
            frm, to = as_list(exp.get("frm")), as_list(exp.get("to"))
            for oid in frm:
                claim_a.setdefault(oid, []).append(where)
            for oid in to:
                claim_b.setdefault(oid, []).append(where)
            check(len(set(frm)) == len(frm),
                  f"{where}: `frm` repeats {sorted({o for o in frm if frm.count(o) > 1})!r}; "
                  "a repeated id is one occurrence written twice, not two partners")
            check(len(set(to)) == len(to),
                  f"{where}: `to` repeats {sorted({o for o in to if to.count(o) > 1})!r}; "
                  "a repeated id is one occurrence written twice, not two partners")
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
            licensed_rules.update(lic)
            if exp.get("reason"):
                exercised_reasons.add(exp["reason"])
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
                # BOTH HALVES: the empty counterpart AND the anchor. Checking only
                # the counterpart accepted a refusal about NO occurrence at all -
                # `{side: b, frm: null, to: []}` passed, and aggregate accounting
                # did not notice because another expectation already claimed the B
                # occurrence. A refusal that names nobody says nothing; step 0
                # requires exactly one on the primary side and so does this.
                if exp.get("side") == "b":
                    check(exp.get("frm", "missing") is None,
                          f"{where}: an unresolved(b) leaves `frm` NULL per "
                          f"finding-lineage/v1, got {exp.get('frm', 'missing')!r}. An "
                          "empty list is a different claim, and normalising it here "
                          "would hide the divergence rather than allow it.")
                    check(len(to) == 1,
                          f"{where}: an unresolved(b) must name exactly one occurrence "
                          f"in revision B, got {to!r}")
                else:
                    check(exp.get("to") == [],
                          f"{where}: an unresolved(a) leaves `to` EMPTY per "
                          f"finding-lineage/v1, got {exp.get('to')!r}")
                    check(len(frm) == 1,
                          f"{where}: an unresolved(a) must name exactly one predecessor, "
                          f"got {frm!r}")
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

            # A STRUCTURAL RECORD MUST BE CARRIED TOO, and must name these
            # occurrences - the same duty the defeat loop below imposes, which
            # until now applied to defeaters alone. A rule may be declared
            # applicable while `revision_b.copies` names two unrelated files;
            # nothing looked, so `branched` rested on a record about somebody
            # else. The quantifier comes from the rule's `record_binding`, never
            # from the checker: copy explains ONE successor and fold names EVERY
            # predecessor, and a checker picking either on its own would be
            # holding an opinion about the policy.
            # LICENSED rules are bound against THIS mapping's group. The
            # quantifiers live inside one entry: a fold split into
            # `WireA -> WireA` and `WireB -> WireA` describes two separate folds,
            # and two records do not add up to one transformation.
            for rid in lic:
                rule_r = rules[rid]
                binding = rule_r.get("record_binding")
                if binding is None and (rule_r.get("cardinality") or {}).get("shape") == "1:1":
                    # At 1:1 there is exactly one occurrence in each role, so
                    # `every` and `at_least_one` are the SAME condition and the
                    # checker chooses no policy by applying it - see
                    # `record_binding_vocabulary.at_one_to_one`.
                    binding = {"predecessor": {"quantifier": "every"},
                               "successor": {"quantifier": "every"}}
                if not binding:
                    continue
                for kind in (rule_r.get("requires_all") or []):
                    sig = kind if kind in catalog else kind_records.get(kind)
                    cat_s = catalog.get(sig)
                    if not cat_s:
                        continue
                    read_field, entries, pairs = catalog_read(cat_s, rev_b)
                    check(bool(entries),
                          f"{where}: {rid} rests on {sig!r}, but {read_field} carries "
                          "nothing. A record cited by a licensing rule and absent from "
                          "revision B is a record asserted in a note.")
                    pools = {}
                    for role in ("predecessor", "successor"):
                        spec_r = binding.get(role) or {}
                        pool = list(frm if role == "predecessor" else to)
                        if spec_r.get("excluding") == "partners_where_same_path_holds":
                            others = to if role == "predecessor" else frm
                            paths = {by_id.get(o, {}).get("path") for o in others}
                            pool = [o for o in pool
                                    if by_id.get(o, {}).get("path") not in paths]
                            check(bool(pool),
                                  f"{where}: {rid} excludes partners at the "
                                  f"predecessor's path and no {role} is left. The record "
                                  "would then explain nothing this mapping needs.")
                        pools[role] = pool

                    def carries(entry: dict) -> bool:
                        rel = related_by(entry, pairs, pools["predecessor"],
                                         pools["successor"], by_id)
                        for role in ("predecessor", "successor"):
                            quant = (binding.get(role) or {}).get("quantifier")
                            reached = {p[0 if role == "predecessor" else 1] for p in rel}
                            if quant == "every" and any(o not in reached
                                                        for o in pools[role]):
                                return False
                            if quant == "at_least_one" and not reached:
                                return False
                        return True

                    def shown(ids_):
                        return [by_id.get(o, {}).get("enclosing_symbol")
                                or by_id.get(o, {}).get("path") for o in ids_]
                    check(any(carries(e) for e in entries),
                          f"{where}: {rid} rests on {sig!r}, and no SINGLE entry of "
                          f"{read_field} relates this mapping as its `record_binding` "
                          f"requires. Predecessors {shown(pools['predecessor'])!r}, "
                          f"successors {shown(pools['successor'])!r}; the records hold "
                          f"{entries!r}. Two records describing two transformations do "
                          "not add up to one transformation.")

            # A REFUSED CONFLICT LICENSES NOTHING, and the loop above therefore
            # skipped it entirely - so `copy-source-that-is-also-a-fold-refuses`
            # kept its `conflicting-evidence` while its copy record pointed at
            # `Other/Nope.cs`. Half the conflict the case preregisters was not
            # carried by the fixture at all. Scoping to `lic` fixed a real error
            # (the refusal's `frm`/`to` are the unresolved record's own sides, not
            # a group) and quietly dropped this coverage with it.
            #
            # What is checkable here is weaker, and the limit is the point: the
            # record must RELATE some pair of this fixture's occurrences, so it is
            # about them rather than about unrelated files. It is NOT checked
            # against the rule's quantifiers, because the group an unlicensed rule
            # would have formed is applicability, and this suite does not compute
            # it. Applying the fixture-wide occurrence set to `every` would reject
            # this very case: the fold names neither `DocCopyView.Wire` nor the
            # copy target, correctly, because they are the other half of the
            # conflict.
            for rid in sorted(set(app) - set(lic)):
                for kind in (rules[rid].get("requires_all") or []):
                    sig = kind if kind in catalog else kind_records.get(kind)
                    cat_s = catalog.get(sig)
                    if not cat_s:
                        continue
                    read_field, entries, pairs = catalog_read(cat_s, rev_b)
                    check(bool(entries),
                          f"{where}: {rid} is applicable on {sig!r}, but {read_field} "
                          "carries nothing")
                    touched = set()
                    for entry in entries:
                        touched |= related_by(entry, pairs, sorted(occ_a),
                                              sorted(occ_b), by_id)
                    check(bool(touched),
                          f"{where}: {rid} is declared applicable on {sig!r}, and no "
                          f"entry of {read_field} relates ANY occurrence of this case "
                          f"to another. The records hold {entries!r}, which describe a "
                          "transformation somewhere else. A rule that establishes half "
                          "of a refused conflict has to be carried by the fixture like "
                          "any other.")

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

            for sig in as_list(exp.get(UNAVAILABLE_FIELD)):
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

            # The candidate binding the contract promises: rule id -> the ids it
            # could not choose between. Checked where it appears, and required
            # wherever a rule is recorded as unable to choose - otherwise the
            # promise in `reason_mapping.several_candidates` stays unkeepable.
            # BOTH DIRECTIONS. This required the binding only when a rule was
            # recorded as unable to choose, so the converse - candidates named for
            # a rule that no stage rejected - passed. That is not cosmetic: the
            # recall union is built from the rejecting fields, so candidates
            # attached to nothing put a rule's ambiguity in the record while
            # leaving it out of the recall set, and `mandated_reason` reads no
            # blunted rule and can still demand `no-mapping-evidence`. The field
            # is the candidate binding FOR the uniqueness rejection; with no
            # rejection there is nothing for it to bind.
            # RAW LISTS FIRST. Every consumer below turns these into sets, so a
            # repeated id vanished and two different serialised records - one
            # naming a rule once, one twice - both passed. A record is what a
            # mapper writes down; the checker must not be more forgiving about
            # its shape than the thing reading it.
            for field in ("conflicting_rules", "rules_without_a_unique_candidate",
                          "rules_excluded_by_cardinality"):
                raw_f = detail.get(field)
                if isinstance(raw_f, list):
                    rep = sorted({i for i in raw_f if raw_f.count(i) > 1})
                    check(not rep,
                          f"{where}: decision_detail.{field} repeats {rep!r}. The set "
                          "comparisons below cannot see it, and a consumer that counts "
                          "the array disagrees with this suite.")
            for _rid, _ids in (detail.get("ambiguous_candidates") or {}).items():
                if isinstance(_ids, list):
                    rep = sorted({i for i in _ids if _ids.count(i) > 1})
                    check(not rep,
                          f"{where}: ambiguous_candidates[{_rid!r}] repeats {rep!r}; one "
                          "candidate written twice is not two candidates")

            cand = detail.get("ambiguous_candidates")
            blunted_ids = detail.get("rules_without_a_unique_candidate") or []
            if blunted_ids or cand:
                check(isinstance(cand, dict) and set(cand) == set(blunted_ids),
                      f"{where}: decision_detail.ambiguous_candidates must name the "
                      "candidates for exactly the rules recorded in "
                      f"rules_without_a_unique_candidate {sorted(blunted_ids)}, got "
                      f"{sorted(cand or {})}")
            for rid, ids_ in (cand or {}).items():
                check(rid in rules, f"{where}: ambiguous_candidates names unknown rule {rid!r}")
                check(isinstance(ids_, list) and len(set(ids_)) >= 2,
                      f"{where}: {rid} is recorded as unable to choose between "
                      f"{ids_!r}; fewer than two candidates is not an ambiguity")
                for oid in ids_ or []:
                    check(oid in occ_a or oid in occ_b,
                          f"{where}: candidate {oid!r} is in neither revision")

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
                    met |= bool(exp.get(UNAVAILABLE_FIELD))
                elif duty == "rule_licensed_alone":
                    # The rule is not merely present, it is the ONLY thing present.
                    # `licensed_by` alone would be satisfied by a rule riding along
                    # with a second one that did the real work, which is exactly the
                    # incidental reach this obligation exists to rule out.
                    met |= len(app_s) == 1 and app_s == lic_s
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

        for side, claims in (("A", claim_a), ("B", claim_b)):
            for oid, wheres in sorted(claims.items()):
                check(len(wheres) == 1,
                      f"{name}: revision {side} occurrence {oid!r} is claimed by "
                      f"{len(wheres)} expectations ({', '.join(wheres)}). One "
                      "occurrence gets one decision; two is a contradiction "
                      "preregistered as though it were a matrix.")
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
    # frozen in name only and a mapper may reach it however it likes.
    #
    # What stood here was an ARGUMENT FOR NOT CHECKING PER RULE: that this matrix
    # is about shapes where two answers are available, that a rename which simply
    # works is not one, and that R-CONT-RENAME is constrained by the senior corpus
    # instead. Every clause of that was wrong. `finding-lineage/v1` fixtures name
    # no decision rule ids and this suite never arbitrates them, so the senior
    # corpus constrains no rule here at all; R-CONT-RENAME and R-CONT-DRIFT were
    # both reached by nothing, and either could be rewritten into a different
    # policy - `path_rename` for `same_path`, `line_drift` for `path_rename` -
    # with the suite staying green. The exemption was not an oversight; it was
    # reasoned for, in this comment, and the reasoning is what let the gap sit.
    # A declared refusal with no case is a decision nothing pins - the defect this
    # project keeps finding in its own drafts. The N:M pair was frozen in the
    # contract and exercised by no fixture at all until this check was written.
    for pair in sorted(({frozenset(c["between"]) for c in
                         policy["deliberately_unresolved_conflicts"]}), key=sorted):
        check(pair in exercised_refusals,
              f"the declared refusal {sorted(pair)} is exercised by no preregistered "
              "case. A conflict the contract deliberately refuses is a decision, and a "
              "decision with no case is frozen in name only.")

    # EVERY EMITTED REASON, not merely every outcome. The outcome gate read
    # `unresolved` as covered while two of its five reasons - `ambiguous-candidates`
    # and `insufficient-evidence-kind` - were pinned by no fixture at all. The
    # first is what `arbitration.multiplicity` selects; the second is the
    # below-floor half of the distinction the senior contract was amended to
    # carry. Both branches could be repointed without turning this suite red.
    for reason in sorted(emitted):
        check(reason in exercised_reasons,
              f"no preregistered case reaches {reason!r}. The policy can emit it, so "
              "something has to pin which condition selects it - an outcome gate "
              "cannot, because several reasons share one outcome.")

    for wanted in sorted({rules[r]["outcome"] for r in ids} | {"unresolved"}):
        check(wanted in licensed_outcomes,
              f"no preregistered case reaches {wanted!r}; the policy can license it and "
              "nothing pins how")

    # PER RULE, because per outcome is not enough: four rules license `continued`,
    # so exercising any one of them ticked the outcome off and left the other
    # three free to be rewritten. See `rule_coverage_rule` in the contract for
    # what this gate does NOT establish - reaching a rule is not the same as
    # binding its `requires_all` to the evidence, which is applicability and is
    # not this suite's to compute.
    for rid in sorted(ids):
        check(rid in licensed_rules,
              f"{rid} licenses nothing in the matrix. The policy declares it, so its "
              "requirements can be changed into a different rule and no preregistered "
              "case would notice - which is how two of these rules were found.")

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

    # THE CASE TABLE, ROW BY ROW. "Mentions every case" left the table free to
    # number itself however it liked, and the prose above it claimed `Ten` while
    # the rows ran to 12. A count restated in prose goes stale exactly as often as
    # it is restated, so the number now lives only in the table - and the table is
    # checked against the contract instead of being trusted.
    doc_rows = re.findall(r"^\|\s*(\d+)\s*\|\s*`([a-z0-9-]+)`\s*\|",
                          doc, re.M)
    check([int(n) for n, _ in doc_rows] == list(range(1, len(preregistered) + 1)),
          f"the doc's case table is numbered {[n for n, _ in doc_rows]}; "
          f"`preregistered_cases` holds {len(preregistered)} cases, so the rows must "
          "run 1..N with no gap and no repeat")
    check([c for _, c in doc_rows] == list(preregistered),
          "the doc's case table lists\n  "
          + "\n  ".join(c for _, c in doc_rows)
          + "\nbut `preregistered_cases` is\n  "
          + "\n  ".join(preregistered)
          + "\nSame cases in the same order, or the table is describing a different "
            "matrix than the one that runs.")

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
