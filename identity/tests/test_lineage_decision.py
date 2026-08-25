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

# The ONE implementation of `finding-pattern/v1`, imported rather than restated.
# A second copy of `sha1(path + rule + message)` here would be a second identity
# function, and the whole reason this branch needed a sixth senior amendment is
# that nobody was checking fixture ids against the first one.
from identity import pattern as finding_pattern  # noqa: E402
# The duplicate-key scanner, now shared with the senior suite rather than
# living here and being copied there. See `identity/tests/jsonscan.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jsonscan import duplicate_json_keys  # noqa: E402
# ...and the ONE producer of identity limitations, for the same reason. The
# eligibility corpus asserts that a null occurrence id came with a reason
# `occurrence.py` actually emits; a hand-copied list of tokens here would be a
# second vocabulary, and the fixture would then be checked against the copy.
from identity import occurrence as finding_occurrence  # noqa: E402

LIMITATION_VOCABULARY = frozenset(
    v for k, v in vars(finding_occurrence).items()
    if k.startswith("LIMIT_") and isinstance(v, str))

SENIOR = os.path.join(ROOT, "contracts", "finding-lineage-v1.json")
POLICY = os.path.join(ROOT, "contracts", "finding-lineage-decision-v1.json")

# The record field for unevaluable signals, read from the contract that DECLARES
# it rather than repeated here. `unavailable_inputs.recorded_as` used to be prose
# and this name was a literal at three call sites, so the two could drift apart
# with nothing to object - the contract could point a mapper at `signals_defeated`
# and every check stayed green. Now there is one source and it is the contract's.
def _recorded_as() -> str:
    """The field name the contract reserves for unevaluable signals, read without
    a crash.

    This is MODULE level: it runs on import, before `main()` and therefore before
    the contract gate that exists to refuse a malformed contract once and let the
    diagnosis be printed. Deleting `recorded_as` raised KeyError here, three
    hundred lines above the gate, and took every other finding of that run with
    it - a gate cannot protect what runs before it, which is a thing worth
    knowing about gates.

    It stays the CONTRACT'S name and not a default: a value this cannot read
    comes back empty, the gate refuses the contract by name, and the run stops
    before anything reads a fixture through it. There is still one source."""
    try:
        with open(POLICY, encoding="utf-8") as fh:
            value = json.load(fh).get("unavailable_inputs", {}).get("recorded_as")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


UNAVAILABLE_FIELD = _recorded_as()
FIXDIR = os.path.join(ROOT, "identity", "fixtures", "lineage-decision")
# The eligibility corpus is SEPARATE on purpose. Its cases are not relations -
# they have no predecessor and no successor, because the identity an edge would
# have to name is the thing that is missing. Keeping them out of the relation
# corpus is what stops the relation schema being relaxed to admit a null id,
# which would let someone preregister an edge the policy cannot answer.
ELIGDIR = os.path.join(ROOT, "identity", "fixtures", "lineage-eligibility")
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
    needs = set(list_or_empty(rule.get("requires_all")))
    profile = mapping_or_empty(rule.get("partner_profile"))
    return needs | set(list_or_empty(profile.get("requires_all")))


# WHICH RECORD FIELDS EACH SELECTOR BRANCH IS OBSERVED FROM. One table: the
# predicate in `mandated_reason` is built from it and the contract's declared
# `observed_from` is checked against it, so a branch cannot read one field while
# the frozen document names another.
SELECTOR_FIELDS = {
    "conflicting_rules_present": ("applicable_rules",
                                  "decision_detail.conflicting_rules"),
    "ambiguous_candidates_present": ("decision_detail.rules_without_a_unique_candidate",
                                     "decision_detail.ambiguous_candidates"),
    "a_defeat_left_no_surviving_rule": ("signals_defeated",),
    "otherwise": (),
}


def mandated_reason(exp, mapping, floor, senior, selector=None):
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
        spec = mapping_or_empty(mapping.get(key))
        if "reason" in spec:
            return spec["reason"]
        by = mapping_or_empty(spec.get("reason_by_surviving_kinds"))
        if surviving_kinds is None:
            return None
        return by.get("at_or_above_the_floor"
                      if clears_floor(surviving_kinds, senior, floor)
                      else "below_the_floor")

    app = exp.get("applicable_rules") or []
    defeated = exp.get("signals_defeated") or {}
    unavailable = as_list(exp.get(UNAVAILABLE_FIELD))
    detail = exp.get("decision_detail") or {}
    blunted = detail.get("rules_without_a_unique_candidate") or []
    conflicting = detail.get("conflicting_rules") or []
    ambiguous = detail.get("ambiguous_candidates") or {}

    # THE ORDER IS THE CONTRACT'S, READ NOT RESTATED. This used to refuse the
    # moment two rejecting stages fired at once - correctly, because nothing
    # ranked them and choosing here would have been a checker settling a policy
    # question. `reason_selector` ranks them now, so the refusal is replaced by
    # reading the ranking.
    #
    # `rules_excluded_by_cardinality` is DELIBERATELY not a condition of any
    # branch. A cardinality filter says a rule does not govern this shape; it is
    # not a statement about the evidence and it selects no reason. It stays in
    # the record for the recall set - see `reason_selector.cardinality_selects_no_reason`.
    # THE FIELDS EACH BRANCH READS, from `SELECTOR_FIELDS` - the same table the
    # contract's `observed_from` is checked against, so the declaration and the
    # predicate cannot describe different fields. They could before: pointing the
    # ambiguity branch's `observed_from` at `signals_defeated` left the suite green
    # and the frozen selector telling a mapper to look in the wrong place. Both
    # reviewers found it independently.
    def reads(path: str):
        node = exp
        for seg in path.split("."):
            node = mapping_or_empty(node).get(seg) if isinstance(node, dict) else None
        return node
    holds = {when_k: (True if not fields_k
                      else any(reads(f) for f in fields_k))
             for when_k, fields_k in SELECTOR_FIELDS.items()}
    says = {
        "conflicting_rules_present": ("conflicting_rules", "rules applied and disagreed"),
        "ambiguous_candidates_present": ("several_candidates",
                                         "rules matched and singled nobody out"),
        "a_defeat_left_no_surviving_rule": ("no_rule_applied_after_a_defeat", None),
        "otherwise": ("no_rule_applied", "nothing licensed a link"),
    }
    for step in list_or_empty(selector):
        when = mapping_or_empty(step).get("when")
        if when == "eligibility_refused":
            continue          # stage 0 never reaches the relation corpus
        if not isinstance(when, str) or when not in holds:
            return None, (f"`reason_selector` names condition {when!r}, which this "
                          "suite cannot evaluate from a record. An order it cannot "
                          "read is an order it is not applying")
        if not holds[when]:
            continue
        key, why_ = says[when]
        if key == "no_rule_applied_after_a_defeat":
            surv = {k for k in (exp.get("evidence_surviving") or []) if isinstance(k, str)}
            return (of(key, surv),
                    f"a defeat left {len(surv)} kind(s) against a floor of {floor}")
        if unavailable and key == "no_rule_applied":
            why_ = "a signal could not be evaluated"
        return of(key), why_
    return None, ("`reason_selector.order` ran out without matching. It has to end in "
                  "a branch that always holds, or a record exists that the policy "
                  "assigns no reason")


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


# The two ends of a mapping. Written once: `record_binding` role keys, the
# catalog's `matches` values and the binding pools all name the same two, and
# three literal spellings of one vocabulary is how this contract has gone wrong
# before.
SUBJECT_ROLES = ("predecessor", "successor")


def mapping_or_empty(value) -> dict:
    """The value if it IS a mapping, an empty one otherwise - never a crash.

    `(x or {})` was the spelling at seventeen reader sites. It handles `null` and
    `{}` and dies on `"1:1"`, which is how a rule whose `cardinality` was edited
    into a string killed the whole run: the integrity check that reports exactly
    that fault had already recorded it, and the traceback threw the report away
    along with every other violation the run had left to find.

    The fixture reader is gated - a malformed fixture is refused before any
    consumer sees it - and the CONTRACT reader is not, so ten of those sites were
    reading an ungated file. This does not report anything; the checks that own
    each field already do. What it guarantees is that they get to finish."""
    return value if isinstance(value, dict) else {}


def list_or_empty(value) -> list:
    """The list half of the same question, asked the same way."""
    return value if isinstance(value, list) else []


def signal_bindings(spec: dict) -> list:
    """(read path, subject role, subject attribute) for each key the catalog's
    `matches` names, for the roles a mapping actually has.

    A role outside `SUBJECT_ROLES` is DROPPED here rather than handed on. It is
    reported by name where the catalog is validated; what this guarantees is that
    no downstream reader can be given one. `related_by` indexes `subject[role]`
    directly, so writing `succesor.path` in the catalog killed the whole run on a
    KeyError - the contract-integrity check above it had already reported the
    fault, and the crash then threw that report away along with everything else
    the run had left to say.

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
    for key, subject in mapping_or_empty(spec.get("matches")).items():
        role, _, attr = str(subject).partition(".")
        if role not in SUBJECT_ROLES:
            continue
        read = f"{field}[].{key}" if isinstance(shape, dict) else field
        out.append((read, role, attr))
    return out


def boundary_hits(spec: dict, frm, to, by_id: dict, rev_b: dict) -> tuple:
    """(role, the occurrences this boundary actually applied to) - asked once.

    It was asked twice at different strengths, which is this branch's signature
    defect arriving in the boundary block. The declared-defeat validation
    required the boundary to have applied to EVERY occurrence on its side; the
    converse check requires a defeat when it applied to ANY. A fold falsifies the
    stronger one: `merged` names two predecessors, only one of whose enclosing
    symbols is in `removed_symbols`, and the other is the symbol the fold merged
    INTO. Demanding it applied to both rejects the one shape the fixture exists
    to preregister.

    `at least one` is what the guard was for - "defeating a boundary that never
    applied to the side it names proves nothing" - and it still says that. What
    it stops claiming is that a boundary reaching one member of a group must
    reach all of them, which the senior contract nowhere says: the boundary is a
    fact about an occurrence's site, not about the group it was decided with."""
    role, _, attr = str(spec.get("match", "")).partition(".")
    if role not in SUBJECT_ROLES or not attr:
        return role, []
    subjects = frm if role == "predecessor" else to
    observed = collect(rev_b, str(spec.get("observable_from", "")))
    return role, [oid for oid in subjects if by_id.get(oid, {}).get(attr) in observed]


def token_failures(where: str, declared, value) -> list:
    """One `entry_shape` token against one value: list-or-scalar, then member type.

    Shared by the two forms a declaration takes - a shape per key for records
    like `copies`, and one shape for the whole entry where the entries are bare
    values like `reformatted_paths`. It was written for the first form only, and
    the second was therefore not read at all."""
    out = []
    wants_list = isinstance(declared, str) and declared.startswith("list of")
    if wants_list != isinstance(value, list):
        out.append(
            f"{where} is {value!r}, and `entry_shape` declares it {declared!r}. A "
            "scalar written as a one-element list reads the same to a lenient parser "
            "and differently to a literal one, so the corpus would sanction a record "
            "the contract does not.")
        return out
    want_type = int if declared == "int" else str
    members = value if wants_list else [value]
    wrong = [m for m in members if not isinstance(m, want_type)
             or isinstance(m, bool)]
    if wrong:
        out.append(
            f"{where} holds {wrong!r}, and `entry_shape` declares {declared!r}. A "
            "record whose types differ from the catalog is one a mapper parses "
            "differently than the contract describes.")
    return out


def entry_shape_failures(where: str, cat_spec: dict, entries) -> list:
    """The catalog's `entry_shape` says whether a field is a scalar or a list.

    Nothing enforced it. `record_names` accepts a scalar by equality and a list by
    membership - which is right, because a fold's `from` IS a list and a copy's is
    not - and that tolerance quietly became the only reading: turning
    `copies[].from` from a path into `["path"]` left the suite green while
    `entry_shape` declared a scalar. A mapper parsing the contract literally and
    a mapper parsing it leniently would then disagree about the same frozen
    corpus, which is what `entry_shape` exists to prevent."""
    out = []
    shape = cat_spec.get("entry_shape")
    if not isinstance(entries, list):
        return out
    # A WHOLE-ENTRY SHAPE IS A SHAPE. This returned immediately unless
    # `entry_shape` was an object, so `reformatted_paths` - whose entries are
    # bare paths rather than records - was read by nothing here, and rewriting
    # its declaration from `path` to `list of paths` left the suite green while
    # the corpus went on supplying scalars. The class check one section down
    # cannot see it either: both tokens name the same class, which is exactly
    # what makes the cardinality half a separate question.
    # And it makes `entry_shape_rule` - "read of every key against the real
    # records in the frozen corpus" - a claim wider than the check under it,
    # which is the shape this file keeps having to repair.
    if not isinstance(shape, dict):
        for index, entry in enumerate(entries):
            out.extend(token_failures(f"{where}[{index}]", shape, entry))
        return out
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            out.append(f"{where}[{index}] is {entry!r}, not an object")
            continue
        # BOTH DIRECTIONS OF THE KEY SET. Only the declared keys were looked for,
        # so a record could carry a field the schema does not mention and the
        # schema stayed silent about it. `entry_shape` is the record's SCHEMA -
        # `matches` says which fields bind a relation, which is a different
        # question - and a schema that describes part of a record is the same
        # half-reading as a check that covers part of what it declares. The
        # corpus is what binds the key set, so it has to bind it exactly.
        for stray in sorted(set(entry) - set(shape)):
            out.append(f"{where}[{index}] carries {stray!r}, which `entry_shape` "
                       f"declares nothing about. The catalog is the schema a mapper "
                       "parses the record with; a field outside it is a field two "
                       "readers will disagree over.")
        for key, declared in shape.items():
            # EVERY DECLARED KEY, and its TYPE. This skipped a missing key and
            # compared only list-versus-scalar, so deleting `similarity` or
            # writing it as `"100"` left a record violating the shape the catalog
            # declares for it. `entry_shape` says what a record IS; checking one
            # of its three claims is the shape this branch keeps repeating.
            if key not in entry:
                out.append(f"{where}[{index}] omits {key!r}, which `entry_shape` "
                           f"declares as {declared!r}. A mapper reading the catalog "
                           "expects the field to be there.")
                continue
            out.extend(token_failures(f"{where}[{index}].{key}", declared,
                                      entry[key]))
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


def shown_ids(ids_, by_id: dict) -> list:
    """Occurrences named the way a reader recognises them."""
    return [by_id.get(o, {}).get("enclosing_symbol") or by_id.get(o, {}).get("path")
            for o in ids_]


def quantifiers_hold(binding: dict, pools: dict, rel: set) -> bool:
    """The quantifiers of one binding, asked of a set of related pairs."""
    for role in SUBJECT_ROLES:
        quant = mapping_or_empty(binding.get(role)).get("quantifier")
        reached = {p[0 if role == "predecessor" else 1] for p in rel}
        if quant == "every" and any(o not in reached for o in pools[role]):
            return False
        if quant == "at_least_one" and not reached:
            return False
    return True


def coverage_holds(coverage, binding: dict, pools: dict, rels: list) -> bool:
    """The quantifiers under ONE reading of how the record entries combine.

    Module level, and taking `coverage` as an argument rather than reading it
    off the binding, because the discrimination sweep has to ask the SAME
    question under a value the rule did not declare. A second copy of these two
    readings written for the sweep would be a sweep that proves the copy agrees
    with itself."""
    if coverage == "union_of_entries":
        return quantifiers_hold(binding, pools, set().union(*rels) if rels else set())
    if coverage == "single_entry":
        return any(quantifiers_hold(binding, pools, r) for r in rels)
    return False


def split_one_partner_each(entries: list, pairs: list) -> list:
    """Every multi-valued matched field spread over one entry per value.

    The transform a fold record must not survive: `from: [A, B]` becomes two
    records naming one source each, which describes two folds into the same
    successor rather than the one transformation the mapping claims."""
    out = []
    keys = {key for key, _, _ in pairs}
    for entry in entries:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        multi = [k for k in sorted(keys)
                 if isinstance(entry.get(k), list) and len(entry[k]) > 1]
        if not multi:
            out.append(entry)
            continue
        for key in multi:
            for value in entry[key]:
                out.append({**entry, key: [value]})
    return out


COVERAGE_TRANSFORMS = {
    "none": lambda entries, pairs: list(entries),
    "split_records_one_partner_each": split_one_partner_each,
}


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


KIND_TESTS = {
    "string": lambda v: isinstance(v, str),
    "list": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    # `bool` is an `int` in Python and nowhere else. A fixture writing `true`
    # where a line number belongs is malformed input, not the number one.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "integer-or-null": lambda v: v is None or KIND_TESTS["integer"](v),
    "string-or-list-or-null": lambda v: v is None or isinstance(v, (str, list)),
}


def declared_kind_failure(where: str, value, kind: str, why: str = "") -> str:
    """"Is this value the KIND its declaration says?" - asked once.

    It was asked in a dozen hand-written places and never asked at all in most
    of them, and the two spellings that existed disagreed: one branch tested
    `isinstance(value, list)` and reported, another tested it and merely
    returned. Callers pass their own `why`, because the reason a wrong container
    is dangerous differs by field and the argument is worth keeping; the QUESTION
    does not differ and is no longer written twice."""
    if KIND_TESTS[kind](value):
        return ""
    return f"{where} is {value!r}, not {kind}." + (f" {why}" if why else "")


def record_sources(*contracts) -> set:
    """Every `revision_b.<field>` either contract declares a signal observable
    from.

    Hand-listing the record sources would have made a third place that must be
    updated when a signal is added - and of the two that already exist, one was
    missing `rename_record` for a whole round. The contracts say where a signal
    is read FROM; this reads that declaration rather than restating it."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "observable_from" and isinstance(value, str):
                    head, _, rest = value.split("[].")[0].partition(".")
                    if head == "revision_b" and rest:
                        found.add(rest)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for contract in contracts:
        walk(contract)
    return found


# The whole vocabulary of a decision fixture, and the KIND each field holds.
# An undeclared key is a failure: a field added to a fixture and not to these
# tables would reopen exactly the hole they close, and reopen it in silence.
FIXTURE_KINDS = {
    "case": "string", "title": "string", "contract": "string",
    "status": "string", "why": "string",
    "revision_a": "object", "revision_b": "object",
    "expect": "list", "forbid": "list",
}
REVISION_KINDS = {"revision": "string", "occurrences": "list"}
OCCURRENCE_KINDS = {
    "occurrence_id": "string", "path": "string", "enclosing_symbol": "string",
    "anchored_content": "string", "pattern_id": "string",
    # THE INPUTS TO `pattern_id`, without which it cannot be checked. Their
    # absence is what let twelve fixtures write `pat-A` at two different paths -
    # a value `finding-pattern/v1` cannot produce - and so hid the fact that both
    # group rules were unsatisfiable on real data. `pattern_id` is a pure
    # function of these three fields; withholding two of them left the one
    # contract that could falsify the corpus with nothing to read.
    "rule": "string", "message": "string",
    "start_line": "integer", "start_column": "integer-or-null",
}
# EVERY attribute the policy reads off an occurrence, because a MISSING one is
# read as a value. `by_id` indexes `occurrence_id` directly and an occurrence
# without it killed the run; the other five are read with `.get`, which is worse
# - an absent `path` makes `same_path` compare None against a string and come out
# false, so the fixture would witness "the paths differ" by not saying what they
# are. That is absence of a record read as a semantic outcome, which is the one
# thing this whole contract exists to forbid. `start_column` is the exception on
# purpose: nothing reads it.
OCCURRENCE_REQUIRED = frozenset(OCCURRENCE_KINDS) - {"start_column"}
EXPECTATION_KINDS = {
    "outcome": "string", "side": "string", "reason": "string", "note": "string",
    # A predecessor is one occurrence or, for a fold, several. `to` is a list at
    # every outcome, including the empty one.
    "frm": "string-or-list-or-null", "to": "list",
    "applicable_rules": "list", "licensed_by": "list", "evidence_surviving": "list",
    UNAVAILABLE_FIELD: "list",
    "not_applicable": "object", "signals_defeated": "object",
    "boundary_defeated": "object", "decision_detail": "object",
    # occurrence id -> the rule that reaches it, for partners a record binding
    # excluded. Same shape as `signals_defeated` and `boundary_defeated`: the
    # thing, and what explains it.
    "excluded_partners_reached_by": "object",
}
DETAIL_KINDS = {
    "conflicting_rules": "list", "rules_without_a_unique_candidate": "list",
    "rules_excluded_by_cardinality": "list", "ambiguous_candidates": "object",
}
# signal or rule id -> a sentence. The KEYS are checked against their
# vocabularies elsewhere; this table is only about the VALUES.
NAMED_REASON_FIELDS = ("not_applicable", "signals_defeated", "boundary_defeated")


# The eligibility corpus's own vocabulary. Same discipline as the relation
# schema: declared keys only, each of its kind, and an undeclared key is a
# failure rather than a field nobody reads.
ELIGIBILITY_KINDS = {
    "case": "string", "contract": "string", "status": "string", "title": "string",
    "why": "string", "revision": "string", "finding": "object", "expect": "object",
    "forbid": "list",
}
ELIGIBILITY_FINDING_KINDS = {
    "occurrence_id": "string-or-list-or-null", "path": "string", "rule": "string",
    "message": "string", "pattern_id": "string", "enclosing_symbol": "string",
    "anchored_content": "string", "start_line": "integer",
    "start_column": "integer-or-null", "identity_limitations": "list",
}
# NO `frm` AND NO `to`, and their absence is enforced by this table rather than
# assumed: an undeclared key fails, so a fixture cannot quietly grow the edge
# fields that `eligibility.forbids` rules out.
ELIGIBILITY_EXPECT_KINDS = {
    "outcome": "string", "reason": "string", "matched_rules": "list",
    "applicable_rules": "list", "licensed_by": "list",
}
# THE PROHIBITION VOCABULARY. `eligibility.forbids` names the ways a mapper
# could mint the identity `occurrence.py` refused to mint. Each token maps to
# the OUTPUT FIELDS that would embody it, and that mapping is what makes the
# prohibition checkable: the fields are held out of the expectation schema
# above and out of every eligibility fixture's `expect`.
#
# The declaration this replaced was four sentences of prose. Nothing read them:
# swapping all four for `["anything", "else"]` left the eligibility corpus and
# this suite green - a check covering part of what its declaration claims, which
# is the defect shape this branch has now found more than a dozen times, sitting
# inside the section that was added to close another instance of it.
#
# `occurrence_id` is forbidden in `expect` and REQUIRED in `finding`: the stage
# refuses because the input has no identity, and the prohibition is on the
# mapper answering with one it made up, not on the input stating its absence.
ELIGIBILITY_FORBIDDEN_FIELDS = {
    "synthetic_occurrence_id": ("occurrence_id",),
    "ordinal_standing_in_for_identity": ("ordinal", "index", "position"),
    "anchor_hash_standing_in_for_identity": ("anchor_hash", "physical_anchor",
                                             "anchor_id"),
    "null_endpoint_as_pseudo_reference": ("frm", "to"),
}


def kind_table_failures(where: str, obj, kinds: dict, required=frozenset()) -> list:
    """One object against one table: declared keys only, each of its kind, and
    the ones a reader indexes rather than `.get`s actually there."""
    bad = declared_kind_failure(
        where, obj, "object",
        "Nothing below can report what is wrong with a fixture whose sections "
        "are not sections.")
    if bad:
        return [bad]
    out = []
    for key in sorted(obj):
        if key not in kinds:
            out.append(f"{where}.{key} is not a field this fixture schema declares. "
                       "Either the field is a typo the suite would read as absent, or "
                       "the schema has drifted behind the fixtures - and an undeclared "
                       "field is an unchecked one.")
            continue
        msg = declared_kind_failure(f"{where}.{key}", obj[key], kinds[key])
        if msg:
            out.append(msg)
    for key in sorted(required - set(obj)):
        out.append(f"{where} omits {key!r}. Every reader below either indexes it "
                   "directly or reads it with `.get` and compares the result - so "
                   "leaving it out does not raise a question, it answers one.")
    return out


def fixture_shape_failures(name: str, case, senior: dict, policy: dict) -> list:
    """Every container in a decision fixture is the KIND its schema declares -
    asked once, before any reader sees the fixture.

    Two reviewers each reported one instance of this in the same round: a
    structural record source written as an object rather than a list, and an
    `ambiguous_candidates` value written as a bare integer. Both were real, and
    fixing the two named sites would have been the mistake this branch has now
    made seven times. A census replaced every field of every fixture, one at a
    time, with a scalar, an empty object and an empty list: of 2637 mutations,
    633 crashed the suite and 625 left it green. A crash reports NOTHING - not
    this violation and not the twenty others that run would have found - so the
    two reported sites were two of 1258.

    With this gate the same census crashes 0 and leaves 38 green, and those 38
    are four known classes, not a residue: `start_column`, which is declared
    `integer-or-null` and legitimately accepts an integer; the ELEMENTS of
    `removed_symbols`, a senior-contract source no decision-layer signal reads;
    and an `evidence_surviving` or `inputs_unavailable` emptied on ONE
    expectation while a sibling expectation still carries it, which asks whether
    an obligation binds the case or each expectation - a question about
    `case_obligations`, not about shape.

    KIND, in BOTH directions. A list written as a scalar and a scalar written as
    a list are one defect, and checking the direction a reviewer happened to send
    is how the last several rounds each left half a fix behind.

    KIND ONLY. Whether a field must be PRESENT, and whether its contents are well
    formed, are different questions, asked by `entry_shape_failures`,
    `malformed_list_failures` and the passes in `main`. This one answers what a
    field IS, so that those may assume it."""
    kinds = dict(FIXTURE_KINDS)
    revision_kinds = dict(REVISION_KINDS,
                          **{src: "list" for src in record_sources(senior, policy)})
    out = kind_table_failures(name, case, kinds)
    if out:
        return out
    for side in ("revision_a", "revision_b"):
        if side not in case:
            continue
        # THE TABLE, THEN WHAT IT LICENSES. `... or []` walked whatever
        # `occurrences` happened to be, so a scalar `occurrences` - the very
        # thing the table above reports - was iterated one line after being
        # reported, and the TypeError killed the run before the report reached
        # anyone. That is the seventh time on this branch that a guard has died
        # on the input it exists to describe. Nothing here reads a section the
        # table has not first agreed is that kind of section.
        rev_bad = kind_table_failures(f"{name}.{side}", case[side], revision_kinds)
        out += rev_bad
        if rev_bad:
            continue
        for index, occ in enumerate(case[side].get("occurrences") or []):
            out += kind_table_failures(f"{name}.{side}.occurrences[{index}]",
                                       occ, OCCURRENCE_KINDS, OCCURRENCE_REQUIRED)
    for index, forbidden in enumerate(case.get("forbid") or []):
        msg = declared_kind_failure(f"{name}.forbid[{index}]", forbidden, "string",
                                    "`forbid` states in words what the case must NOT "
                                    "conclude; a container states nothing.")
        if msg:
            out.append(msg)
    for index, exp in enumerate(case.get("expect") or []):
        where = f"{name}[{index}]"
        entry = kind_table_failures(where, exp, EXPECTATION_KINDS)
        out += entry
        if entry:
            continue
        for field in NAMED_REASON_FIELDS + ("decision_detail",):
            # DECLARED, AND NOT EMPTY - the question `populated_object_failure`
            # was written for, asked here rather than answered a second way.
            # Three of these four happened to be caught by a later pass that
            # wanted their contents; `boundary_defeated: {}` was caught by
            # nothing, and a case declaring that a boundary was defeated and
            # naming no boundary says less than a case that stays silent.
            if field in exp:
                bad = populated_object_failure(f"{where}.{field}", exp[field])
                if bad:
                    out.append(bad)
        for field in NAMED_REASON_FIELDS:
            for key in sorted(exp.get(field) or {}):
                msg = declared_kind_failure(
                    f"{where}.{field}[{key!r}]", exp[field][key], "string",
                    "The value is the sentence saying why, and it is the only "
                    "place that reason is written down.")
                if msg:
                    out.append(msg)
        detail = exp.get("decision_detail")
        if detail is None:
            continue
        detail_bad = kind_table_failures(f"{where}.decision_detail", detail, DETAIL_KINDS)
        out += detail_bad
        if detail_bad:
            continue
        for rid in sorted(detail.get("ambiguous_candidates") or {}):
            msg = declared_kind_failure(
                f"{where}.ambiguous_candidates[{rid!r}]",
                detail["ambiguous_candidates"][rid], "list",
                "It holds the candidates a rule could not choose BETWEEN, so "
                "fewer than two of anything is not an ambiguity - and a scalar "
                "here is iterated further down and kills the run.")
            if msg:
                out.append(msg)
    return out


def malformed_list_failures(where: str, exp: dict, unavailable_field: str) -> list:
    """Every declared list on an expectation holds STRINGS - checked before
    anything reads them.

    Review reported one crash site: a set built from raw list values. Fixing that
    one left the suite still dying, because the assumption is everywhere - a
    `{...}` element reached a set comprehension in `mandated_reason`, an integer
    element reached `rules[rid]` as a key. Patching each site as it surfaced would
    have been the mistake this branch keeps making; the assumption is stated once,
    here, and the caller skips an expectation that fails it.

    A suite that dies on the evidence it came to read reports NOTHING - not the
    malformed field, and not the twenty other things that fixture might also get
    wrong. That is strictly worse than a suite that says what is wrong and
    continues, which is why this is a guard rather than a repair."""
    out = []
    fields = ["frm", "to", "applicable_rules", "licensed_by", "evidence_surviving",
              unavailable_field]
    detail = exp.get("decision_detail")
    for field in fields:
        value = exp.get(field)
        if value is None or isinstance(value, str):
            continue
        if not isinstance(value, list):
            out.append(f"{where}: `{field}` is {value!r}, not a list")
            continue
        bad = [v for v in value if not isinstance(v, str)]
        if bad:
            out.append(f"{where}: `{field}` holds non-string entries {bad!r}. Every "
                       "consumer treats these as ids or kind names, and several put "
                       "them in a set or a dict key - so the suite would die here "
                       "rather than tell you which field is malformed.")
    # THE CONTAINERS, BEFORE THEIR CONTENTS. This entered the dict branch and
    # otherwise said nothing, so a `decision_detail` that was a string sailed
    # past and died later on `.get`; and `ambiguous_candidates` was iterated with
    # `.items()` before anything checked it was a mapping, so a list died HERE -
    # inside the guard written to stop the suite dying. A guard that assumes the
    # shape it was added to doubt is not a guard.
    if detail is not None and not isinstance(detail, dict):
        return [f"{where}: `decision_detail` is {detail!r}, not an object. Everything "
                "that reads it expects a mapping, so nothing below can report what is "
                "wrong with this fixture."]
    if isinstance(detail, dict):
        cand_ = detail.get("ambiguous_candidates")
        if cand_ is not None and not isinstance(cand_, dict):
            return [f"{where}: `decision_detail.ambiguous_candidates` is {cand_!r}, not "
                    "an object. It maps a rule id to the candidates it could not choose "
                    "between; a bare list names candidates for no rule."]
        for field in ("conflicting_rules", "rules_without_a_unique_candidate",
                      "rules_excluded_by_cardinality"):
            value = detail.get(field)
            # THE CONTAINER FIRST. This validated elements only when the value
            # already WAS a list, so an object went unremarked - and `set(...)`
            # over a dict iterates its keys, so a mapping whose keys happen to be
            # the right rule ids satisfied every comparison downstream. The check
            # covered the contents of its claim and not the claim.
            if value is not None and not isinstance(value, list):
                out.append(f"{where}: decision_detail.{field} is {value!r}, not a list "
                           "of rule ids. An object here passes every set comparison "
                           "below, because a set of a mapping is a set of its keys.")
                continue
            if isinstance(value, list):
                bad = [v for v in value if not isinstance(v, str)]
                if bad:
                    out.append(f"{where}: decision_detail.{field} holds non-string "
                               f"entries {bad!r}")
        for rid_, ids_ in mapping_or_empty(detail.get("ambiguous_candidates")).items():
            if isinstance(ids_, list):
                bad = [v for v in ids_ if not isinstance(v, str)]
                if bad:
                    out.append(f"{where}: ambiguous_candidates[{rid_!r}] holds "
                               f"non-string entries {bad!r}")
    return out


def repeats_failure(where: str, seq) -> str:
    """"Does this declared list repeat an entry?" - asked once.

    It was asked in eleven hand-written places, in three spellings, and two
    record fields a mapper writes were never asked at all: `evidence_surviving`
    and the unavailable-inputs list. Both are consumed through `set()`, so a
    repeat changed no verdict here while sanctioning two raw shapes for one
    provenance record - the identical argument review made for the
    `decision_detail` arrays, which was accepted and fixed in the three fields it
    named. The class was not closed then; this closes it.

    Returns "" when the value is not a list: whether a field must BE a list is a
    different question, asked where that field is read."""
    if not isinstance(seq, list):
        return ""
    # BY EQUALITY, never through a set or a sort. This helper runs BEFORE the
    # field-specific validators that check element types, so a fixture holding
    # `[{...}, {...}]` raised `unhashable type: dict` and `[1, 1, "R-X", "R-X"]`
    # raised on comparing str with int - the suite dying on the evidence it came
    # to read, which this file already records as a failure it has had before and
    # which the last commit reintroduced by building a set from raw input.
    rep = []
    for i, item in enumerate(seq):
        if any(item == other for other in seq[:i]):
            continue
        if sum(1 for other in seq if other == item) > 1 and item not in rep:
            rep.append(item)
    if rep:
        return (f"{where} repeats {rep!r}. Every consumer normalises this through "
                "`set()`, so the repeat changes no verdict and still leaves two raw "
                "spellings of one record - and anything that counts the array "
                "disagrees with this suite.")
    return ""


# The senior field the floor comes from, named ONCE. `floor_spec_failures` binds
# the contract's declaration to this same constant, so the check cannot pass
# because it happens to agree with a different reading of the same key.
FLOOR_FIELD = "minimum_evidence_kinds_for_continued"
# The only counting semantics `clears_floor` implements. A contract declaring
# another one would be describing a policy this suite does not check.
FLOOR_COUNTED_OVER = "distinct_kinds"


WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12}


def prose_number_failures(policy: dict, senior: dict) -> list:
    """Prose that restates a number this contract also declares as data.

    This branch has watched a restated count go stale three times: the case count
    twice, and the floor sentence in `reason_mapping` once - the last of which was
    load-bearing, since a mapper reading it classified evidence the suite
    classified the other way. `preregistration_rule` already records the remedy
    for its own count: "THE LIST ABOVE IS THE COUNT, and this paragraph does not
    repeat it." Nothing applied that to the floor or the outcome count, which are
    restated across both contracts.

    WHAT THIS DOES NOT DO, since a gate claiming more than it checks is this
    branch's most-found defect: it catches a restatement written in one of the
    forms below and disagreeing with the data. Prose that restates the same number
    some other way is not caught, and no check here can promise otherwise - the
    honest fix for that is not to restate the number."""
    out = []
    floor = senior[FLOOR_FIELD]
    outcomes_n = len(senior["outcomes"])
    def numbers(text):
        for raw in re.findall(r"floor of ([a-z]+|\d+)", text, re.I):
            yield "floor", raw
        for raw in re.findall(r"([a-z]+|\d+) outcomes", text, re.I):
            yield "outcomes", raw
    def walk(node, trail, source):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, trail + [k], source)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, trail + [f"[{i}]"], source)
        elif isinstance(node, str):
            for kind, raw in numbers(node):
                value = WORD_NUMBERS.get(raw.lower())
                if value is None and raw.isdigit():
                    value = int(raw)
                if value is None:
                    continue
                want = floor if kind == "floor" else outcomes_n
                if value != want:
                    out.append(
                        f"{source} :: {'.'.join(trail)} says {raw!r} where the "
                        f"{kind} is {want}. A number restated in prose goes stale "
                        "exactly as often as it is restated, and one such sentence "
                        "here already contradicted the senior rule it described.")
    walk(policy, [], "finding-lineage-decision/v1")
    walk(senior, [], "finding-lineage/v1")
    return out


def floor_spec_failures(policy: dict, senior: dict) -> list:
    """The contract's own statement of the floor, bound to the senior rule.

    `clears_floor` implements the exception; this checks the contract SAYS it.
    Prose restating a rule goes stale exactly as often as it is restated - the
    fifth site of this one was a sentence in `reason_mapping`, still describing a
    bare count after four checker sites had been corrected."""
    out = []
    spec = mapping_or_empty(mapping_or_empty(mapping_or_empty(
        policy.get("reason_mapping")).get("no_rule_applied_after_a_defeat")
    ).get("reason_by_surviving_kinds")).get("floor")
    if not isinstance(spec, dict):
        return [f"`reason_mapping.no_rule_applied_after_a_defeat` states its floor as "
                f"{spec!r}. A prose restatement cannot be checked against the senior "
                "rule, and this one had already drifted from it."]
    # EXACTLY the field, not merely a field that exists. `in senior` accepted
    # `limitations` and `outcomes` - real senior keys, unrelated to the floor -
    # so the contract could claim its refusal threshold derives from the
    # limitation vocabulary and nothing objected. Membership standing in for the
    # correct member, in the check written to stop the contract and the checker
    # disagreeing about this very number.
    if spec.get("senior_field") != FLOOR_FIELD:
        out.append(f"the floor names senior field {spec.get('senior_field')!r}; the "
                   f"suite reads the floor from {FLOOR_FIELD!r} and the contract has to "
                   "name the same one, or the two describe different thresholds while "
                   "agreeing that a threshold exists")
    if spec.get("counted_over") != FLOOR_COUNTED_OVER:
        out.append(f"the floor is counted over {spec.get('counted_over')!r}; "
                   f"`clears_floor` counts {FLOOR_COUNTED_OVER!r} and implements no "
                   "other semantics, so any other value describes a policy nothing "
                   "here checks")
    if spec.get("sufficient_alone_clears") is not True:
        out.append("the floor declares `sufficient_alone_clears` "
                   f"{spec.get('sufficient_alone_clears')!r}. `evidence_rule` in the "
                   "senior contract says such a kind alone satisfies the floor and the "
                   "count stops applying; a junior contract cannot say otherwise.")
    return out


def clears_floor(kinds, senior: dict, floor: int) -> bool:
    """Does this evidence clear `minimum_evidence_kinds_for_continued`?

    Asked in four places - a rule's `requires_all`, a partner profile, the reason
    a defeat mandates, and the arithmetic behind that reason - and until now
    written four times. Three of them counted distinct kinds and stopped there,
    which is right only while every kind is `sufficient_alone: false`.
    `evidence_rule` in the senior contract says the rest: "if a kind is ever
    promoted to `sufficient_alone: true`, that kind alone satisfies the floor and
    the count stops applying to it."

    The fix for that sentence landed at ONE of the four sites. A fixture whose
    defeat left a single promoted kind was then classified below the floor by the
    reason checks and above it by the rule checks, in one run. Fixed at one level
    and not asked at the next, in the commit that was itself correcting a
    contradiction with this same sentence."""
    kinds = set(kinds or ())
    if any(mapping_or_empty(senior["evidence_kinds"].get(k)).get("sufficient_alone")
           for k in kinds):
        return True
    return len(kinds) >= floor


def evidence_list_failures(where: str, kinds, senior: dict, catalog: dict,
                          floor: int, allow_records: bool, need_floor: bool,
                          forbid_sufficient_alone: bool) -> list:
    """One validation for every list of evidence a rule rests on.

    `requires_all` and `partner_profile.requires_all` are the same kind of claim
    and were checked twice, by hand, at different strengths - the profile
    rejected an unknown kind and a `sufficient_alone` one, the rule's own list
    rejected neither. A comment above the rule's list even recorded noticing one
    half of that gap ("`partner_profile` already got this right") and fixed only
    the half it named.

    The `sufficient_alone` exclusion is a PARAMETER, not a shared rule, and the
    reason is worth keeping. Unifying these two lists, an earlier revision applied
    the profile's exclusion to rule requirements as well - reasoning that it was
    fail-closed and that the argument generalised. Both reviewers rejected it, and
    both were right: `evidence_rule` in the senior contract says in terms that "if
    a kind is ever promoted to `sufficient_alone: true`, that kind alone satisfies
    the floor and the count stops applying to it". Forbidding such a kind from
    `requires_all` made the decision policy unable to express an evolution the
    senior contract explicitly provides for - a junior contract contradicting its
    senior from below, which is the one thing this layering forbids.

    The profile keeps the exclusion because it rests on a different claim, already
    argued in `partner_profile_rule`: a profile describes what each repeated
    partner shows ON ITS OWN, and one strong signal is not a profile. That does
    not generalise to a rule-level combination, and "fail-closed" was not a reason
    to assume it did.

    Sharing structure is not sharing every rule. The point of one function is that
    the common checks cannot drift apart, not that the differences vanish."""
    out = []
    if not isinstance(kinds, list) or not kinds:
        out.append(f"{where} must NAME the kinds it rests on, got {kinds!r}")
        return out
    for kind in kinds:
        known = kind in senior["evidence_kinds"] or (allow_records and kind in catalog)
        if not known:
            out.append(f"{where} names {kind!r}, which is neither a frozen evidence "
                       "kind nor a structural signal")
        if (forbid_sufficient_alone
                and mapping_or_empty(senior["evidence_kinds"].get(kind))
                .get("sufficient_alone")):
            out.append(f"{where} rests on {kind!r}, which `finding-lineage/v1` calls "
                       "sufficient alone; a profile of one strong signal is not a "
                       "profile")
    if len(set(kinds)) != len(kinds):
        rep = sorted({k for k in kinds if kinds.count(k) > 1})
        out.append(f"{where} repeats {rep!r}. The floor counts KINDS, so a repeat is "
                   "either a typo or an attempt to reach the floor twice over the same "
                   "evidence.")
    # THE FLOOR STOPS APPLYING to a kind promoted to `sufficient_alone`, which is
    # the senior contract's own sentence and not a reading of it. A count-only
    # floor rejected a rule resting on one such kind, so the policy could not
    # represent the evolution `evidence_rule` provides for.
    if need_floor and not clears_floor(kinds, senior, floor):
        out.append(f"{where} names {len(set(kinds))} distinct kind(s); the frozen floor "
                   f"is {floor}, and none of them is `sufficient_alone`")
    return out


def populated_object_failure(where: str, value) -> str:
    """"Declared, and not empty" - asked once, wherever it is asked.

    The outer field check learned this the hard way: `{}` and `null` are
    declarations whose value is empty, and every hand-written variant of the test
    let a different one through. The nested ROLE values under `record_binding`
    were then left to `if not isinstance(v, dict): continue`, so `null`, `[]` and
    `0` skipped quantifier validation in silence - the same defect one level in,
    in the same field, found by a reviewer the round after the outer half was
    fixed. Both levels call this now."""
    if not isinstance(value, dict) or not value:
        return (f"{where} is {value!r}. It must be a populated object; `null`, `[]`, "
                "`0` and `{}` are all ways of declaring nothing, and each has been "
                "accepted by some hand-written version of this check.")
    return ""


def group_only_field_failures(rid: str, rule: dict, field: str) -> list:
    """One predicate for every field a rule may declare only when it has a GROUP.

    `partner_profile` and `record_binding` are the same claim about two fields,
    and they were written twice. The first time they diverged one was
    biconditional and the other was not; the second time both were biconditional
    and they still disagreed, because one tested `isinstance(v, dict)` and the
    other `bool(v)` - so `{}` was rejected by one and accepted by the other, and
    `null` by neither. Reading alike was not enough. They are one function now.

    PRESENCE, not truthiness and not type. Whether a field is DECLARED is a
    question about the key; `{}` and `null` are declarations whose value happens
    to be empty, and a mapper reading the contract sees a second way of spelling
    "no binding"."""
    out = []
    shape = mapping_or_empty(rule.get("cardinality")).get("shape")
    is_group = shape != "1:1"
    declared = field in rule
    if declared != is_group:
        out.append(
            f"{rid} is {shape!r} and {'declares' if declared else 'omits'} `{field}`, "
            f"which belongs to group rules and only to them. A 1:1 rule has no group "
            f"to describe, and a group rule without one leaves its partners unasked. "
            f"The KEY is the declaration - `{{}}` and `null` are declarations too.")
    elif declared and is_group:
        bad = populated_object_failure(f"{rid}.{field}", rule.get(field))
        if bad:
            out.append(bad)
    return out


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


# What `licensed_by` may be declared to select. Two entries, and the second is
# not decoration: `all_applicable` differs from `undominated_applicable` on
# exactly the subsets where dominance does any work, so the token the contract
# names changes the verdict of the sweep below.
LICENSED_BY_SELECTORS = {
    "undominated_applicable":
        lambda subset, edges: {r for r in subset
                               if not any((w, r) in edges for w in subset)},
    "all_applicable": lambda subset, edges: set(subset),
}
LICENSED_BY_EMPTINESS = ("refusal", "never")


def licensed_by_rule_failures(policy: dict, results: dict, edges, refusals) -> list:
    """The contract's account of `licensed_by`, checked against the procedure.

    It was a paragraph, and the paragraph was checked for EXISTENCE. Replacing it
    with the opposite claim - that `licensed_by` carries every applicable rule,
    dominated ones included - left the whole suite green, so a mapper reading the
    contract and this suite reading `arbitrate` could disagree about the
    provenance every record carries, with nothing to object.

    Same shape as the floor: a sentence that states what some code decides, and
    binds to it only if it is machine-readable. Swept over every subset rather
    than asserted once, because the two selectors agree on most subsets and
    differ precisely where dominance does its work.

    Dominance between rules of ONE outcome is already refused by property 2, so
    the all-agree branch of `arbitrate` returning the whole subset is the
    undominated set on that branch - not a third selector hiding in the code."""
    out = []
    rule = mapping_or_empty(mapping_or_empty(policy.get("arbitration"))
                            .get("licensed_by_rule"))
    selects = rule.get("selects")
    if selects not in LICENSED_BY_SELECTORS:
        return [f"`arbitration.licensed_by_rule.selects` is {selects!r}; the vocabulary "
                f"is {sorted(LICENSED_BY_SELECTORS)}. Prose here was checked for "
                "existence and said nothing, which is why it is a token now."]
    empty_when = rule.get("empty_exactly_when")
    if empty_when not in LICENSED_BY_EMPTINESS:
        return [f"`arbitration.licensed_by_rule.empty_exactly_when` is {empty_when!r}; "
                f"the vocabulary is {list(LICENSED_BY_EMPTINESS)}."]
    if rule.get("dominated_rules_remain_in") != "applicable_rules":
        out.append("`arbitration.licensed_by_rule.dominated_rules_remain_in` must be "
                   "`applicable_rules`; a dominated rule that leaves the record "
                   "entirely takes the disagreement with it, and the recall set is "
                   "the union that has to keep it.")
    select = LICENSED_BY_SELECTORS[selects]
    for subset, result in sorted(results.items(), key=lambda kv: sorted(kv[0])):
        if result is None:
            continue
        outcome_, licensed = result
        refused = any(frozenset(pair) <= subset for pair in refusals)
        if refused:
            if empty_when != "refusal" or licensed:
                out.append(f"{sorted(subset)}: the subset exercises a declared refusal "
                           f"and arbitration licenses {sorted(licensed)!r}. The contract "
                           f"says `licensed_by` is empty exactly when {empty_when!r}.")
            continue
        want = select(subset, edges)
        if set(licensed) != want:
            out.append(f"{sorted(subset)}: arbitration licenses {sorted(licensed)!r}, "
                       f"but `licensed_by_rule.selects` is {selects!r}, which names "
                       f"{sorted(want)!r}. The contract and the procedure disagree "
                       "about which rules the outcome rests on.")
        if empty_when == "never" and not licensed:
            out.append(f"{sorted(subset)}: licenses nothing while the contract says "
                       "`licensed_by` is never empty.")
    return out[:6]


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


# The contract sections this suite indexes into, and the kind each must be.
# Derived from what is READ, not from a restatement of the contract: every entry
# here is a section some check below walks or subscripts.
POLICY_SECTIONS = {
    "rules": "objects", "structural_signals": "objects", "reason_mapping": "objects",
    "signal_defeaters": "objects", "arbitration": "object", "dominance": "object",
    "record_additions": "object", "record_binding_vocabulary": "object",
    "case_obligations": "object", "unavailable_inputs": "object",
    "evidence_kind_records": "object", "eligibility": "object",
    "deliberately_unresolved_conflicts": "list", "preregistered_cases": "list",
}
# Fields INSIDE an entry that the suite reads attribute by attribute. One level
# deeper than the sections, and the level review actually crashed the suite on:
# `rules.R-CONT-SAME-SITE.cardinality` as the string "1:1" is a well-formed rule
# in a well-formed section, and `card.get("shape")` still dies on it.
ENTRY_MAPPING_FIELDS = {
    "rules": ("cardinality", "record_binding", "partner_profile"),
    "structural_signals": ("matches",),
    "reason_mapping": ("reason_by_surviving_kinds",),
    "signal_defeaters": (),
}
SENIOR_SECTIONS = {
    "outcomes": "objects", "evidence_kinds": "objects",
    "boundary_evidence_kinds": "objects", "limitations": "object",
    "mutually_exclusive_evidence_kinds": "list",
}


def contract_shape_failures(policy: dict, senior: dict) -> list:
    """Every contract section this suite reads is the KIND it is read as - asked
    once, before any reader sees it.

    The fixtures have had this gate since the container census; the contracts
    never did, and it is the contracts that three consecutive rounds of review
    kept crashing the suite on. Editing one rule's `cardinality` into the string
    `"1:1"` killed the whole run at `card.get("shape")` - and the integrity check
    that reports exactly that fault had already recorded it, so the traceback
    threw away its own diagnosis along with every other violation the run had
    left to find.

    Three spellings of one guard had to be swept before this was written -
    `(x or {})`, `.get(k, {})` and bare indexing - and each sweep left the next
    spelling behind, which is the argument for a gate rather than a fourth sweep.
    `objects` means a mapping whose VALUES are mappings: `rules` is walked as
    `rules[rid]["outcome"]`, so a rule that is a string is the same defect one
    level down.

    KIND ONLY, and only for sections that are read. What each section must
    CONTAIN is the business of the checks that own it; this exists so that they
    run at all."""
    out = []
    recorded_as = mapping_or_empty(policy.get("unavailable_inputs")).get("recorded_as")
    if not isinstance(recorded_as, str) or not recorded_as:
        out.append(
            "finding-lineage-decision/v1: `unavailable_inputs.recorded_as` is "
            f"{recorded_as!r}. It names the record field for unevaluable signals, and "
            "this suite derives the fixture schema from it AT IMPORT - so a missing "
            "one is read before any check can run and takes the whole run with it.")
    elif recorded_as != UNAVAILABLE_FIELD:
        out.append(
            f"finding-lineage-decision/v1: `unavailable_inputs.recorded_as` is "
            f"{recorded_as!r}, but the schema was built from {UNAVAILABLE_FIELD!r} at "
            "import. The contract changed under the run.")
    for contract, sections, label in ((policy, POLICY_SECTIONS, "finding-lineage-decision/v1"),
                                      (senior, SENIOR_SECTIONS, "finding-lineage/v1")):
        for name, kind in sorted(sections.items()):
            value = contract.get(name)
            if kind == "list":
                if not isinstance(value, list):
                    out.append(f"{label}: `{name}` is {value!r}, not a list. Every "
                               "reader below walks it.")
                continue
            if not isinstance(value, dict):
                out.append(f"{label}: `{name}` is {value!r}, not an object. Every "
                           "reader below subscripts it.")
                continue
            if kind != "objects":
                continue
            for key in sorted(value):
                if not isinstance(value[key], dict):
                    out.append(f"{label}: `{name}.{key}` is {value[key]!r}, not an "
                               "object. It is read attribute by attribute, so a "
                               "reader reaches it before any check can report it.")
                    continue
                for field in ENTRY_MAPPING_FIELDS.get(name, ()):
                    if field in value[key] and not isinstance(value[key][field], dict):
                        out.append(
                            f"{label}: `{name}.{key}.{field}` is "
                            f"{value[key][field]!r}, not an object. The check that "
                            "reports this field records the fault and the run then "
                            "dies reading it, which throws the report away.")
    return out


def main() -> int:
    senior = load(SENIOR)
    policy = load(POLICY)
    # BEFORE EVERY READER, and nothing runs on a contract that failed it. `check`
    # accumulates rather than stopping, so reporting a malformed section and
    # carrying on is how the report gets discarded by the traceback it predicted.
    shape = contract_shape_failures(policy, senior)
    for msg in shape:
        check(False, msg)
    if shape:
        print(f"identity/lineage-decision: FAIL - {len(fails)} check(s) failed")
        for msg in fails:
            print(f"FAIL: {msg}")
        return 1

    rules = policy["rules"]
    ids = sorted(rules)
    outcomes = {r: rules[r]["outcome"] for r in ids}
    raw_edges = raw_dominance_edges(policy)
    for msg in prose_number_failures(policy, senior):
        check(False, msg)
    for msg in floor_spec_failures(policy, senior):
        check(False, msg)
    for msg in refusal_shape_failures(policy):
        check(False, msg)
    raw_refusals = raw_refusal_pairs(policy)
    edges = set(raw_edges)
    refusals = {frozenset(r) for r in raw_refusals}

    # ---- 0. The policy is subordinate, enforced from ABOVE. -----------------
    # ITS OWN NAME, not only whose it builds on. Every FIXTURE is checked for
    # naming this contract, and the contract itself was never asked - so the
    # frozen policy could be renamed or lose its identifier entirely with both
    # suites green, and twelve fixtures would go on declaring conformance to a
    # document that no longer says what it is. The senior suite has checked this
    # of the senior contract from the start; the junior one is the adjacent site
    # nobody asked, which is now the third time that pairing has produced a
    # finding.
    check(policy.get("contract") == "finding-lineage-decision/v1",
          f"the policy declares itself {policy.get('contract')!r}; the fixtures and "
          "this suite both name `finding-lineage-decision/v1`, and a document that "
          "does not say which schema it is cannot be conformed to.")
    check(senior.get("contract") == "finding-lineage/v1",
          f"the senior contract this policy is read against declares itself "
          f"{senior.get('contract')!r}. `builds_on` names a document; this is the "
          "check that the document loaded IS that one.")
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
    # STAGE 0 EMITS A REASON TOO. It is not in `reason_mapping` because it is not
    # reached by mapping evidence to a refusal - it is settled before any evidence
    # is read - but a reason the policy can emit has to be pinned by a case like
    # any other, and leaving it out of this set is how `missing-occurrence-id` sat
    # frozen in the senior contract with no junior path for the whole of step 1.
    emitted.add(mapping_or_empty(policy.get("eligibility")).get("reason"))
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
            want_b = mapping_or_empty(policy["reason_mapping"][key]).get("reason")
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

    conflict_reason = mapping_or_empty(policy["reason_mapping"].get("conflicting_rules")).get("reason")
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
    floor = senior[FLOOR_FIELD]
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
        for msg in evidence_list_failures(
                f"{rid}: requires_all", req_all, senior, policy["structural_signals"],
                floor, allow_records=True, need_floor=outcomes[rid] == "continued",
                forbid_sufficient_alone=False):
            check(False, msg)

        # Cardinality is a PRECONDITION of the rule, so it is checked as one. The
        # alternative - letting `arbitration.multiplicity` overturn a structural
        # rule after it fired - puts one question in two sections.
        card = rules[rid].get("cardinality")
        check(isinstance(card, dict) and "shape" in card,
              f"{rid} declares no `cardinality`; a mapper would have to guess whether "
              "the rule is 1:1, and guessing is how a lone successor gets `branched`")
        if isinstance(card, dict):
            shape = card.get("shape")
            # READ OFF THE SENIOR CONTRACT, not restated next to a sentence
            # claiming the senior contract says so. The three shapes stood here
            # as the literals "1:1", "1:N" and "N:1", so `outcomes.continued`
            # could be edited upstairs to 1:N and this check went on enforcing
            # 1:1 while its own message cited the file it had stopped agreeing
            # with. A junior contract may not narrow senior from below; a junior
            # CHECKER restating senior is the same move one level down, and it
            # keeps its answer when senior changes its mind. Found by mutating
            # the senior contract: both suites stayed green.
            # `isinstance`, not `or {}`. The truthy spelling handles `null` and
            # `{}` and dies on `42` - the same half-guard this branch has now
            # written eight times, and it died on the senior contract, which is
            # the input this check exists to read.
            senior_spec = senior["outcomes"].get(outcomes[rid])
            senior_card = (senior_spec.get("cardinality")
                           if isinstance(senior_spec, dict) else None)
            check(isinstance(senior_card, str),
                  f"the senior contract gives outcome {outcomes[rid]!r} no `cardinality` "
                  f"string, so there is nothing for {rid} to be checked against")
            if isinstance(senior_card, str):
                check(shape == senior_card,
                      f"{rid} licenses {outcomes[rid]} at cardinality {shape!r}; the "
                      f"senior contract makes {outcomes[rid]} {senior_card!r}")
            # The MINIMUM on the plural side, keyed on the shape rather than on
            # the outcome name - the shape is what says which side is plural.
            # Two is not read from senior: senior says "several", which is prose,
            # and `min_successors` is the junior contract's own reading of it.
            if shape == "1:N":
                check(card.get("min_successors", 0) >= 2,
                      f"{rid} licenses {outcomes[rid]} without requiring two successors; "
                      "a group of one is a 1:1 under another name")
            elif shape == "N:1":
                check(card.get("min_predecessors", 0) >= 2,
                      f"{rid} licenses {outcomes[rid]} without requiring two predecessors")

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
        for msg in group_only_field_failures(rid, rules[rid], "partner_profile"):
            check(False, msg)
        if isinstance(card, dict):
            # IF AND ONLY IF. This required a profile of group rules and forbade
            # one nowhere, so a 1:1 rule could declare `partner_profile` - which
            # names the REPEATED side, of which it has none - and `rule_needs`
            # would silently fold those kinds into its requirements. The sibling
            # `record_binding` check was written biconditional; this one was not,
            # and the two sat four lines apart.
            pass
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
                mapping_or_empty(rules[rid].get("cardinality")).get("shape"))
            if repeated:
                check(prof.get("per") == repeated,
                      f"{rid} is {mapping_or_empty(rules[rid].get('cardinality')).get('shape')!r}, so "
                      f"the group is its {repeated}s, but `partner_profile.per` is "
                      f"{prof.get('per')!r} - the side there is exactly one of. A profile "
                      "checked against the singleton says nothing about the partners the "
                      "outcome rests on.")
            req = prof.get("requires_all") if isinstance(prof, dict) else None
            # A profile names SENIOR kinds only: a structural record is what the
            # group rule itself rests on, not what each partner shows alone.
            for msg in evidence_list_failures(
                    f"{rid}: partner_profile", req, senior,
                    policy["structural_signals"], floor,
                    allow_records=False, need_floor=True,
                    forbid_sufficient_alone=True):
                check(False, msg)
        # NO RULE MAY REQUIRE AN IMPOSSIBLE COMBINATION. The senior contract
        # freezes which kinds cannot co-occur; a rule demanding both is dead and
        # takes its outcome down quietly with it. This is one of the two things
        # standing in for a binding of `requires_all` to evidence, which the
        # suite cannot do without becoming a second mapper - see the note on
        # `rule_coverage_rule`.
        needs = rule_needs(rules[rid])
        # AND THE COMBINATION CAN BE IMPOSSIBLE WITHOUT BEING WRITTEN DOWN. A kind
        # whose equality fields CONTAIN another kind's entails that kind: comparing
        # `[rule, message, path]` is comparing `[path]` and more. So the exclusive
        # pairs are closed under that entailment before they are applied.
        # This is what makes widening a senior kind a contradiction rather than a
        # preference: `same_rule_message` widened with `path` entails `same_path`,
        # `same_path` is frozen exclusive with `path_rename`, and R-CONT-RENAME
        # requires both - the rule is dead and the existing law says so. Review
        # found the widening by hand; nothing here could object to it, because the
        # field list was checked for being a non-empty list of strings and nothing
        # else, one level below where the same defect was last repaired.
        eq_fields = {k: set(v) for k, v in mapping_or_empty(mapping_or_empty(
            senior.get("pair_property_equality_fields")).get("map")).items()
            if isinstance(v, list) and all(isinstance(f, str) for f in v) and v}
        entailed = set(needs)
        for kind_n, fields_n in eq_fields.items():
            if kind_n in needs:
                entailed |= {other for other, f_o in eq_fields.items()
                             if f_o and f_o <= fields_n}
        for excl in list_or_empty(senior.get("mutually_exclusive_evidence_kinds")):
            pair = set(excl.get("between") or [])
            check(not pair <= entailed,
                  f"{rid} requires {sorted(pair)} together, which "
                  "`finding-lineage/v1` freezes as mutually exclusive. No evidence "
                  "can satisfy the rule, so it licenses nothing and its outcome "
                  "silently degrades to `unresolved`."
                  + ("" if pair <= needs else
                     f" It reaches them through the equality fields the senior "
                     f"contract gives {sorted(needs & set(eq_fields))}: a kind that "
                     "compares everything another kind compares requires that kind "
                     "too."))

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
               mapping_or_empty(rules[rid].get("cardinality")).get("shape"))
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
    for msg in licensed_by_rule_failures(policy, results, edges, refusals):
        check(False, msg)
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
    # ...AND THE ELIGIBILITY CORPUS, which the comment above already claimed was
    # covered by saying "the FIXTURES". It meant one directory. The other arrived
    # later and never joined the list, so an eligibility case could declare
    # `expect` twice - an invalid one first, the valid one second - and lose the
    # invalid half to `json.load` before any check saw it. Verified: injecting a
    # first `expect` naming `continued` left the suite green.
    scanned += [(f"eligibility fixture {f}", os.path.join(ELIGDIR, f))
                for f in sorted(os.listdir(ELIGDIR)) if f.endswith(".json")]
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
    kind_records = mapping_or_empty(policy.get("evidence_kind_records")).get("map") or {}
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
        for key, subject in mapping_or_empty(matches).items():
            role, dot, attr = str(subject).partition(".")
            # Already asked here. What was missing is not the question but the
            # consequence: `check` accumulates, so the run continued into
            # `related_by`, which indexes `subject[role]` and died on a KeyError -
            # throwing away this very report along with everything else the run
            # had left to say. `signal_bindings` now declines to pass an unknown
            # role on, so the report survives to be printed.
            check(role in SUBJECT_ROLES,
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
    NO_RECORD = "no_structural_record"
    observation = {k: v for k, v in
                   mapping_or_empty(senior.get("evidence_kind_observation")).items()
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
        # A `revision_record` classification is a DEMAND for a record, so the
        # contract has to say which one. It said only that the token was in the
        # vocabulary: reclassifying `same_pattern_id` - reached solely through
        # `partner_profile`, and so deliberately outside the kind-to-record map's
        # domain - left the frozen contract demanding a revision record while
        # naming nowhere to read it, with the suite green. Both group rules rest
        # on that kind, so legitimate branch and merge evidence would be refused
        # or resolved ad hoc.
        #
        # No new declaration closes this; the existing ones already contradict
        # each other. Requiring the record to be NAMED makes the classification
        # unsatisfiable for a kind the map cannot carry, which is the right
        # answer rather than a second opinion about which kinds those are.
        if how == "revision_record":
            check(kind_records.get(kind) not in (None, NO_RECORD),
                  f"`evidence_kind_observation[{kind!r}]` says a revision record "
                  "observes it, and `evidence_kind_records.map` names no record for it "
                  f"(got {kind_records.get(kind)!r}). A kind reached only through a "
                  "`partner_profile` is outside that map by design, so classifying one "
                  "this way demands evidence the contract gives no way to read.")

    # EVERY PAIR PROPERTY SAYS WHAT IT COMPARES, in one of two tables, and both
    # are READ. `pair_property_fields` is what the witness obligation reads to
    # decide whether a kind really failed in a case, what the positive reader
    # checks of a licensed relation, and what decides entailment between kinds.
    # It lives in the senior contract because a junior defining what a senior
    # kind compares has redefined the kind - the junior copy this replaces could
    # be widened with `path`, and then a witness whose rule and message AGREED
    # still read as `same_rule_message` failing.
    #
    # TWO TABLES, because not every pair property is an equality. `line_drift`
    # holds when `start_line` DIFFERS. It used to be a one-line note saying so,
    # and every reader here intersected with the equality map - so the note was a
    # BLIND SPOT: a case could license R-CONT-DRIFT with the successor sitting on
    # the predecessor's own line, drift required and absent, and nothing
    # objected. An exclusion list read as a filter and never as a thing needing
    # its own reader is this branch's defect wearing a different hat.
    #
    # TOTAL and PARTITIONED: a kind in neither table is a comparison nobody wrote
    # down, and one in both says two things at once.
    eq_decl = mapping_or_empty(senior.get("pair_property_fields"))
    eq_map = mapping_or_empty(eq_decl.get("equality"))
    df_map = mapping_or_empty(eq_decl.get("difference"))
    pair_kinds = {k for k, how in observation.items() if how == "pair_property"}
    check(pair_kinds == set(eq_map) | set(df_map),
          "`finding-lineage/v1.pair_property_fields` must cover every kind "
          f"`evidence_kind_observation` calls a pair property. Missing "
          f"{sorted(pair_kinds - set(eq_map) - set(df_map))}, unexpected "
          f"{sorted((set(eq_map) | set(df_map)) - pair_kinds)}. A kind in neither "
          "table is a comparison nobody has written down, and both tables are read "
          "to decide whether a kind held in a case.")
    check(not (set(eq_map) & set(df_map)),
          f"`pair_property_fields` puts {sorted(set(eq_map) & set(df_map))} in both "
          "tables. A kind is satisfied by fields AGREEING or by their DIFFERING, "
          "and it cannot be both.")
    for table_n, kinds_n in (("equality", eq_map), ("difference", df_map)):
        for kind_e in sorted(kinds_n):
            fields_e = kinds_n[kind_e]
            check(isinstance(fields_e, list) and fields_e
                  and all(isinstance(f, str) and f in OCCURRENCE_KINDS
                          for f in fields_e),
                  f"`pair_property_fields.{table_n}[{kind_e!r}]` is {fields_e!r}. It "
                  f"has to name occurrence fields out of {sorted(OCCURRENCE_KINDS)} - "
                  "a kind compared on a field the occurrences do not carry is "
                  "compared on nothing.")

    # AND NO KIND IS ANOTHER KIND AND MORE. The floor counts KINDS: two are
    # required for a `continued`. If one equality's fields contained another's, a
    # single observation would satisfy both and meet the floor by itself - which
    # is the argument the sixth senior amendment already made for making
    # `same_rule_message` ONE kind rather than `same_rule` beside `same_message`.
    # Containment is also what the entailment below turns into a contradiction,
    # so requiring the sets to be independent says the same thing at the source.
    for kind_a in sorted(eq_map):
        for kind_b in sorted(eq_map):
            fa, fb = eq_map.get(kind_a), eq_map.get(kind_b)
            if kind_a == kind_b or not isinstance(fa, list) or not isinstance(fb, list):
                continue
            check(not (fb and set(fb) < set(fa)),
                  f"`pair_property_fields.equality` gives {kind_a!r} {fa!r} and "
                  f"{kind_b!r} {fb!r}, so anything satisfying {kind_a!r} satisfies "
                  f"{kind_b!r}. The floor for a `continued` counts KINDS, and two "
                  "kinds one observation cannot separate meet it by themselves - "
                  "which is why the sixth senior amendment made `same_rule_message` "
                  "one kind instead of two halves.")

    # AND THE FIELD SET IS PINNED BY VECTORS. Membership in the occurrence
    # vocabulary, totality and independence are all properties a WRONG set can
    # have, and review demonstrated several: `same_rule_message` extended with
    # `start_line`, `anchored_content` REPLACED by `start_column`. A vector says
    # what the definition says - two occurrences differing in exactly these
    # fields and agreeing on every other one, does the kind hold? - and the
    # subsets consistent with a kind's vectors must number EXACTLY ONE and be the
    # declared list. Thinning them leaves several consistent; editing the list
    # makes it disagree with them. Neither half moves alone.
    #
    # The consistency test differs by table and that is the whole distinction: an
    # equality holds when NONE of its fields is among the ones that differ, a
    # difference holds when ALL of them are.
    eq_vectors = mapping_or_empty(eq_decl.get("vectors"))
    check(set(eq_vectors) == set(eq_map) | set(df_map),
          "`pair_property_fields.vectors` must pin every pair property and only "
          f"those. Missing {sorted((set(eq_map) | set(df_map)) - set(eq_vectors))}, "
          f"unexpected {sorted(set(eq_vectors) - set(eq_map) - set(df_map))}. A kind "
          "whose fields no vector constrains is a definition nothing reads, which is "
          "what these replace.")
    universe = sorted(OCCURRENCE_KINDS)
    for kind_v in sorted(set(eq_vectors) & (set(eq_map) | set(df_map))):
        rows = eq_vectors[kind_v]
        rows = rows if isinstance(rows, list) else []
        is_diff = kind_v in df_map
        ok_rows = []
        for index_v, row in enumerate(rows):
            row = mapping_or_empty(row)
            differs, holds = row.get("differs_in"), row.get("holds")
            good = (isinstance(differs, list) and differs
                    and all(isinstance(f, str) and f in OCCURRENCE_KINDS
                            for f in differs)
                    and isinstance(holds, bool))
            check(good,
                  f"`pair_property_fields.vectors[{kind_v!r}][{index_v}]` is "
                  f"{row or None!r}. A vector names a non-empty set of occurrence "
                  "fields the two occurrences differ in, and says whether the kind "
                  "holds - anything else constrains nothing.")
            if good:
                ok_rows.append((set(differs), holds))
        consistent = [frozenset(c) for n in range(len(universe) + 1)
                      for c in itertools.combinations(universe, n)
                      if c and all((set(c) <= d if is_diff else not (set(c) & d)) == h
                                   for d, h in ok_rows)]
        declared_v = (df_map if is_diff else eq_map).get(kind_v)
        declared_v = (frozenset(declared_v) if isinstance(declared_v, list)
                      and all(isinstance(f, str) for f in declared_v) else None)
        check(consistent == [declared_v],
              f"`pair_property_fields` declares {kind_v!r} as "
              f"{sorted(declared_v) if declared_v else declared_v!r}, and its vectors "
              f"admit {[sorted(c) for c in consistent[:4]]}"
              f"{' and more' if len(consistent) > 4 else ''}. The vectors have to "
              "leave exactly one field set standing, and it has to be the one "
              "declared: several means they were thinned until they constrain "
              "nothing, and a different one means the list drifted from the "
              "definition beside it.")

    # AND EVERY PAIR PROPERTY HAS A CASE THAT MAKES IT FAIL. Vectors and the
    # field list agree with each other, and agreement between two declarations is
    # not either of them being bound to data. Three kinds had no failing case, so
    # `anchored_content` could be amended to compare `start_column` - vectors
    # edited to match, every licensed relation still passing, because the column
    # was null on both sides everywhere. A kind nothing can falsify is a
    # definition nothing reads.
    witnessed = {mapping_or_empty(v).get("kind")
                 for k, v in mapping_or_empty(
                     policy.get("required_kind_witnesses")).items()
                 if k != "rule"}
    unwitnessed = sorted((set(eq_map) | set(df_map)) - witnessed)
    check(not unwitnessed,
          f"no case makes {unwitnessed} fail: `required_kind_witnesses` names no "
          "witness for them, so nothing in the corpus is compared on the fields "
          "`pair_property_fields` gives them. The vectors would then agree with the "
          "list and both could move together - which is how a kind gets redefined "
          "into a field that never differs anywhere.")

    # The validated tables, under the names the case loop reads them by. Bound
    # after the checks above so a malformed declaration is reported there rather
    # than silently shaping what a fixture is measured against.
    def _clean(table):
        return {k: list(v) for k, v in table.items()
                if isinstance(v, list) and v
                and all(isinstance(f, str) and f in OCCURRENCE_KINDS for f in v)}
    eq_fields_map, df_fields_map = _clean(eq_map), _clean(df_map)

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
    # A RECORD THAT BINDS A MAPPING HAS TO CONSTRAIN BOTH ENDS OF IT. The loop
    # below checks that a GROUP rule's declared roles equal the catalog's, which
    # covers `copy_record` and `merge_record` - but only transitively, through
    # those rules' own declarations. A 1:1 rule declares no `record_binding` at
    # all, since the field belongs to group rules and only them, so its binding
    # is SYNTHESISED further down with both roles and nothing asked whether the
    # catalog names both. Deleting `rename_record.matches.to` left the suite
    # green, and a rename record whose `from` matched while its `to` pointed at
    # an unrelated file then licensed R-CONT-RENAME: with the successor end
    # unnamed, `related_by` counts every successor as reached.
    #
    # Asked of the records rules REST ON, not of every signal. The two defeaters
    # name one role deliberately - `renamed_symbol_record` matches on `from`
    # alone, because a record saying something ARRIVED at a name is not evidence
    # about the predecessor that left it, and pooling the two roles there was a
    # defect fixed in an earlier round. The contract draws that line itself; this
    # reads it rather than restating it.
    rested_on = set()
    for rule_ in rules.values():
        for kind_ in rule_needs(rule_):
            sig_ = kind_ if kind_ in catalog else kind_records.get(kind_)
            if sig_ in catalog:
                rested_on.add(sig_)
    for sig_ in sorted(rested_on):
        roles_ = {r for _, r, _ in signal_bindings(catalog[sig_])}
        check(roles_ == set(SUBJECT_ROLES),
              f"{sig_} is a record that rules rest on, and its `matches` names "
              f"{sorted(roles_)}. A record explaining a mapping has to constrain BOTH "
              "ends of it: with one end unnamed, every occurrence on that side counts "
              "as reached and the record licenses a mapping it does not describe.")

    # THE SELECTOR'S OWN REASONS, BOUND TO THE BRANCH THEY LABEL. `mandated_reason`
    # enforces the ORDER and takes each reason from `reason_mapping`; the `reason`
    # written beside every step was read by nothing. Setting all four to
    # `no-mapping-evidence` left the suite green, so the contract could declare
    # that an ambiguity yields one reason while the checker applied another - a
    # declared claim nothing checks, inside the section added to close exactly
    # that. Found by review.
    SELECTOR_SOURCE = {
        "conflicting_rules_present": "conflicting_rules",
        "ambiguous_candidates_present": "several_candidates",
        "a_defeat_left_no_surviving_rule": "no_rule_applied_after_a_defeat",
        "otherwise": "no_rule_applied",
    }
    for step in list_or_empty(mapping_or_empty(policy.get("reason_selector")).get("order")):
        when_ = mapping_or_empty(step).get("when")
        said_ = mapping_or_empty(step).get("reason")
        if not isinstance(when_, str):
            continue          # `mandated_reason` reports the malformed token itself
        if when_ == "eligibility_refused":
            want_ = mapping_or_empty(policy.get("eligibility")).get("reason")
        elif when_ in SELECTOR_SOURCE:
            node_ = mapping_or_empty(policy["reason_mapping"].get(SELECTOR_SOURCE[when_]))
            want_ = node_.get("reason") or (
                f"reason_mapping.{SELECTOR_SOURCE[when_]}.reason_by_surviving_kinds"
                if "reason_by_surviving_kinds" in node_ else None)
        else:
            continue          # unknown token: `mandated_reason` refuses it already
        check(said_ == want_,
              f"`reason_selector` step {when_!r} declares reason {said_!r}, and the "
              f"branch it labels yields {want_!r}. The order is enforced and the "
              "reasons beside it were not, so this section could say one thing while "
              "the policy did another - which is the shape it was written to close.")
        # ...and the SAME question about `observed_from`, which was the other
        # unread field beside it.
        saw_ = mapping_or_empty(step).get("observed_from")
        want_f = (["occurrence_id"] if when_ == "eligibility_refused"
                  else sorted(SELECTOR_FIELDS.get(when_, ())))
        check(saw_ == want_f,
              f"`reason_selector` step {when_!r} declares observed_from {saw_!r} and "
              f"the predicate for that branch reads {want_f}. A frozen selector that "
              "names the wrong record field tells a mapper to look somewhere the "
              "decision does not come from, and nothing else in this document "
              "corrects it.")

    # `entry_shape` AGREES WITH `matches`, WHICH IS THE NORMATIVE HALF. An unknown
    # token was already rejected, but a WRONG KNOWN one was not:
    # `copy_record.entry_shape.to = "enclosing symbol"` passed while the record's
    # `to` is a path and `matches` says so. Membership standing in for the correct
    # member, in the structural-signal catalog this time - found by the reader
    # audit, which is the only place it could have been found, since no fixture
    # reads `entry_shape` at all.
    # AN EXACT VOCABULARY, not a substring. `want_word in said_n` accepted
    # `"path-x"`, so the field could say something meaningless and still name the
    # right attribute inside it. Half-checked is what this audit exists to remove.
    #
    # AND EVERY KEY, not only the ones `matches` names. This block ran over
    # `matches` and read `entry_shape` through it, so a key `matches` does not
    # name was read by nothing: `renamed_symbol_record.entry_shape.to` could be
    # rewritten from `enclosing symbol` to `path` and the suite stayed green. That
    # is the same defect one level up from the one this block closes - the keys of
    # one object read THROUGH the keys of another, which covers the intersection
    # and calls it the whole.
    #
    # THE FIX IS TO BIND THE UNMATCHED KEY, NOT TO STRIP IT. `entry_shape` is the
    # record's schema; `matches` says which of its fields take part in relation
    # binding. Reading the schema's domain off `matches` would make a binding
    # declaration into a type definition, which it never was, so an unmatched key
    # stays a full member of the record. What binds its class is what the record
    # IS: these records relate two ends of one move and the two ends are the same
    # kind of thing - a copy path to path, a fold symbols to symbol, a symbol
    # rename name to name. Cardinality may differ across the pair; the class may
    # not. `matches` binding either end therefore binds both.
    # The key SET is bound to the corpus, in both directions, by
    # `entry_shape_failures`: a declared key missing from a record and a record
    # key the schema never declares are both reported there.
    SHAPE_ATTRIBUTE = {"path": "path",
                       "list of paths": "path",
                       "enclosing symbol": "enclosing_symbol",
                       "list of enclosing symbols": "enclosing_symbol",
                       "int": None}
    for sig_n in sorted(policy["structural_signals"]):
        spec_n = mapping_or_empty(policy["structural_signals"][sig_n])
        raw_shape = spec_n.get("entry_shape")
        # A record whose entries are bare values declares one shape for the whole
        # entry rather than a shape per key - `reformatted_paths` is a list of
        # paths. Both forms describe the same thing and both are checked.
        shape_n = mapping_or_empty(raw_shape)
        matches_n = mapping_or_empty(spec_n.get("matches"))

        # EVERY TOKEN IS A TOKEN, matched or not: `entry_shape_failures` reads
        # `list of` and `int` off these words, so one outside the vocabulary is
        # read as neither a list nor a number.
        for key_n, said_n in ([(None, raw_shape)] if not isinstance(raw_shape, dict)
                              else sorted(shape_n.items())):
            token = said_n if isinstance(said_n, str) else None
            where_n = (f"`structural_signals.{sig_n}.entry_shape`" if key_n is None
                       else f"`structural_signals.{sig_n}.entry_shape.{key_n}`")
            check(token in SHAPE_ATTRIBUTE,
                  f"{where_n} is {said_n!r}, which is not one of "
                  f"{sorted(SHAPE_ATTRIBUTE)}. `entry_shape` is read for whether a "
                  "field holds one value or many and whether it is text or a "
                  "number; a word outside the vocabulary is read as neither.")

        # A MATCHED KEY'S CLASS IS THE ATTRIBUTE IT IS MATCHED ON.
        for key_n, subject in sorted(matches_n.items()):
            attr = str(subject).partition(".")[2]
            said_n = raw_shape if not isinstance(raw_shape, dict) else shape_n.get(key_n)
            token = said_n if isinstance(said_n, str) else None
            check(attr and SHAPE_ATTRIBUTE.get(token) == attr,
                  f"`structural_signals.{sig_n}.entry_shape.{key_n}` is {said_n!r} "
                  f"and `matches` binds that key to {subject!r}, so the shape has to "
                  f"name {attr!r}. `matches` is the normative half; a record whose "
                  "declared shape contradicts what it is matched on tells a mapper "
                  "to read the wrong field.")

        # AND THE TWO ENDS OF ONE MOVE ARE THE SAME CLASS. This is what reaches
        # the keys `matches` does not name. It is asked of `from`/`to` wherever
        # both exist rather than of a list the contract declares, because a
        # declaration this check depended on could be deleted to make it vacuous -
        # and an unread key is exactly what is being repaired here.
        if isinstance(raw_shape, dict) and {"from", "to"} <= set(shape_n):
            classes = [SHAPE_ATTRIBUTE.get(shape_n[k]
                                           if isinstance(shape_n[k], str) else None)
                       for k in ("from", "to")]
            check(classes[0] == classes[1] and classes[0] is not None,
                  f"`structural_signals.{sig_n}.entry_shape` says `from` is "
                  f"{shape_n['from']!r} and `to` is {shape_n['to']!r}. A record "
                  "relates the two ends of one move, and the two ends are the same "
                  "kind of thing - a copy goes path to path, a fold symbols to "
                  "symbol, a rename name to name. Cardinality may differ across the "
                  "pair; the class may not, and this is what binds the end no rule "
                  "matches on.")

    # EVERY DECLARED OBLIGATION MEANING IS CARRIED BY SOME CASE. A meaning nothing
    # declares is a duty nobody owes - the same rule this contract already applies
    # to a declared refusal with no case, asked one section over.
    declared_duties = {x for v in mapping_or_empty(
        mapping_or_empty(policy.get("case_obligations")).get("obligations")).values()
        for x in list_or_empty(v) if isinstance(x, str)}
    for duty_n in sorted(mapping_or_empty(
            mapping_or_empty(policy.get("case_obligations")).get("meanings"))):
        check(duty_n in declared_duties,
              f"`case_obligations.meanings` defines {duty_n!r} and no case declares "
              "it. An obligation nobody carries is a duty nobody owes, and it reads "
              "as coverage that is not there.")

    vocab = mapping_or_empty(policy.get("record_binding_vocabulary"))
    # THE VOCABULARY ITSELF, BEFORE ANYTHING IS LOOKED UP IN IT. Membership -
    # `token in vocab["quantifier"]` - raises TypeError when that axis is a
    # scalar, so the three checks that police the binding tokens died on a
    # malformed vocabulary
    # - the guard crashing on the input it exists to examine, for the eleventh
    # time on this branch, and I added the third instance of it here while fixing
    # the tenth somewhere else. Asked once, of all three axes, naming the real
    # defect instead of reporting that some token is "not carried" by a
    # vocabulary that is not a vocabulary.
    axes = {}
    for axis in ("quantifier", "excluding", "coverage"):
        check(isinstance(vocab.get(axis), dict) and bool(vocab[axis]),
              f"`record_binding_vocabulary.{axis}` is {vocab.get(axis)!r}. Every "
              "binding token is checked for membership in it, and membership in a "
              "scalar is not a question with an answer.")
        # A LOCAL READING, not a repair of the loaded contract. Writing the empty
        # mapping back into `policy` would leave every later reader looking at a
        # document this checker quietly fixed.
        axes[axis] = mapping_or_empty(vocab.get(axis))
    for rid in sorted(rules):
        rule_ = rules[rid]
        check("requires_all_scope" not in rule_,
              f"{rid} still carries `requires_all_scope`. It was prose nothing read, "
              "and `record_binding` replaced it; keeping both is two authorities for "
              "one fact, which is how this contract has gone wrong before.")
        binding = rule_.get("record_binding")
        for msg in group_only_field_failures(rid, rule_, "record_binding"):
            check(False, msg)
        if not isinstance(binding, dict) or not binding:
            continue
        structural = [k for k in list_or_empty(rule_.get("requires_all"))
                      if k in policy["structural_signals"]]
        check(len(structural) == 1,
              f"{rid} is a group rule requiring {structural!r} structural signals; "
              "the binding is about exactly one record")
        # HOW THE ENTRIES COMBINE, declared rather than inherited from whichever
        # rule the checker was written for. Required, and with no default: a fold
        # is one record naming all its sources, a copy into N destinations is N
        # records, and reading either as the other licenses a different policy.
        #
        # `axes`, NOT `vocab`, and the message is the reason. The predicate was
        # guarded and this f-string was not, so `sorted(vocab['coverage'])` was
        # evaluated eagerly and the check crashed while REPORTING the fault it had
        # just detected correctly. Twelfth of these, and the first in a message
        # rather than a predicate - a sub-form the previous eleven did not teach
        # me to look for.
        check(binding.get("coverage") in axes["coverage"],
              f"{rid}.record_binding declares coverage {binding.get('coverage')!r}, "
              f"which the vocabulary does not carry. It carries "
              f"{sorted(axes['coverage'])}. A rule that omits it leaves the "
              "quantifier to be read whichever way the checker happens to combine "
              "entries - and on a 1:N copy the two readings are different policies.")
        for sig in structural:
            roles = {r for _, r, _ in signal_bindings(policy["structural_signals"][sig])}
            declared = {k for k in binding if k in SUBJECT_ROLES}
            check(declared == roles,
                  f"{rid}.record_binding names roles {sorted(declared)} but {sig} "
                  f"matches on {sorted(roles)}. The roles are the catalog's, not a "
                  "second opinion about which side the group is on.")
        for role in SUBJECT_ROLES:
            spec_r = binding.get(role)
            if role in binding:
                bad = populated_object_failure(f"{rid}.record_binding.{role}", spec_r)
                check(not bad, bad or "")
            if not isinstance(spec_r, dict) or not spec_r:
                continue
            check(spec_r.get("quantifier") in axes["quantifier"],
                  f"{rid}.record_binding.{role} uses quantifier "
                  f"{spec_r.get('quantifier')!r}, which the vocabulary does not carry")
            if "excluding" in spec_r:
                check(spec_r["excluding"] in axes["excluding"],
                      f"{rid}.record_binding.{role} excludes {spec_r['excluding']!r}, "
                      "which the vocabulary does not carry. Unknown tokens are "
                      "rejected, not ignored.")
                # AND WHAT THE TOKEN ASSUMES, DECLARED. Its `means` promised that a
                # continued rule reaches the partners it drops; the promise is now a
                # named outcome the mapping has to declare applicable.
                excl_spec = mapping_or_empty(axes["excluding"].get(spec_r["excluding"]))
                want_out = excl_spec.get("requires_applicable_outcome")
                check(want_out in set(outcomes.values()),
                      f"`record_binding_vocabulary.excluding.{spec_r['excluding']}` "
                      f"requires applicable outcome {want_out!r}, and no rule here "
                      f"concludes it - the rules conclude "
                      f"{sorted(set(outcomes.values()))}. An exclusion rests on some "
                      "OTHER rule reaching what it drops, so the outcome it names has "
                      "to be one a rule can actually reach; it is named in the "
                      "contract rather than spelled here so the checker does not pick "
                      "which rule rescues an excluded partner.")

    senior_limitations_set = set(senior["limitations"].values())
    unavailable_from = str(policy["unavailable_inputs"].get("observable_from", ""))
    check(unavailable_from.startswith("revision_b."),
          "`unavailable_inputs.observable_from` must name a revision B field, got "
          f"{unavailable_from!r}")
    # EVERY RECORD FIELD THIS SUITE VALIDATES IS DECLARED, and every declaration
    # is a field a fixture may carry. Only `inputs_unavailable` was ever checked
    # for presence here, so `evidence_surviving` and `boundary_defeated` - both
    # required by this suite, both validated in detail, both written by any
    # conforming mapper - appeared in NEITHER contract. That is
    # `requires_all_scope` inverted: prose nothing read became code nothing
    # declared, and a mapper following the contract would have omitted two fields
    # whose absence the suite treats as a violation.
    #
    # `not_applicable` and `note` are deliberately not asserted either way.
    # Whether a mapper writes them, or whether they are annotations the fixtures
    # carry for the reader, is a question the contract has not answered, and
    # answering it here would be the checker deciding what belongs in a record.
    validated_record_fields = {"applicable_rules", "licensed_by", "decision_detail",
                               "signals_defeated", UNAVAILABLE_FIELD,
                               "evidence_surviving", "boundary_defeated",
                               "excluded_partners_reached_by"}
    missing_declarations = sorted(validated_record_fields - set(policy["record_additions"]))
    check(not missing_declarations,
          f"`record_additions` does not declare {missing_declarations}, which this "
          "suite requires of an expectation and validates. A field enforced here and "
          "described nowhere is a field a conforming mapper would not write.")
    undeclared_fields = sorted(set(policy["record_additions"]) - set(EXPECTATION_KINDS))
    check(not undeclared_fields,
          f"`record_additions` declares {undeclared_fields}, which no expectation may "
          "carry. A record field nothing can hold is a promise to a mapper that the "
          "corpus cannot keep.")

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
    coverage_inputs: dict = {}
    for name in sorted(set(on_disk) & set(preregistered)):
        with open(os.path.join(FIXDIR, f"{name}.json"), encoding="utf-8") as fh:
            case = json.load(fh)
        # BEFORE EVERY READER, and the FIRST of them. The malformed-input guard
        # below this loop already learned that refusing per-reader protects one
        # reader; it was hoisted to cover the expectations, and the passes ABOVE
        # where it landed - the identity checks, the entry-shape walk, the
        # occurrence census, `by_id` - still read a revision no one had looked
        # at. A fixture whose `occurrences` is a scalar killed the entire run at
        # `by_id`, and a killed run reports nothing at all.
        shape = fixture_shape_failures(name, case, senior, policy)
        for msg in shape:
            check(False, msg)
        if shape:
            continue
        check(case.get("case") == name, f"{name}: case field is {case.get('case')!r}")
        check(case.get("contract") == "finding-lineage-decision/v1",
              f"{name}: wrong contract {case.get('contract')!r}")
        check(case.get("status") == "preregistered-unimplemented",
              f"{name}: a decision fixture stays preregistered until a mapper exists")
        check(len(case.get("why", "")) > 40, f"{name}: `why` must state what the case defends")
        check(bool(case.get("expect")), f"{name}: nothing is preregistered")

        rev_a, rev_b = case.get("revision_a", {}), case.get("revision_b", {})
        # The catalog declares each record's shape; the fixtures have to hold it.
        for _sig, _spec in sorted(catalog.items()):
            _field = str(_spec.get("observable_from", "")).split("[].")[0]
            if not _field.startswith("revision_b."):
                continue
            for msg in entry_shape_failures(f"{name}: {_field}", _spec,
                                            rev_b.get(_field.partition(".")[2])):
                check(False, msg)
        # EVERY pattern_id RECOMPUTED, not trusted. `finding-pattern/v1` is
        # `sha1(path + rule + message)`, so a fixture's id is checkable and was
        # checked by nothing: twelve cases wrote the opaque `pat-A` at two
        # different paths, and that single fiction concealed a contract defect
        # both reviewers eventually found by reading `identity/pattern.py`
        # instead - both group rules required `same_pattern_id` of a partner
        # whose path had just changed, which no real corpus can satisfy.
        #
        # This is not applicability. It computes no evidence kind and decides no
        # rule; it asks the corpus to be consistent with the identity function
        # this repository already ships, which is the difference between reading
        # a contract and having an opinion about one.
        for side, rev in (("A", rev_a), ("B", rev_b)):
            for occ in rev.get("occurrences", []):
                want = finding_pattern.pattern_id(occ["path"], occ["rule"],
                                                  occ["message"])
                check(occ["pattern_id"] == want,
                      f"{name}: revision {side} {occ['occurrence_id']} declares "
                      f"pattern_id {occ['pattern_id']!r}, but `finding-pattern/v1` "
                      f"computes {want!r} from its path, rule and message. An id the "
                      "identity function cannot produce is a fixture asserting a hash "
                      "collision to make a rule look satisfiable.")

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

        # FAIL AND SKIP THE WHOLE FIXTURE, never crash. This guard used to sit
        # inside the expectation loop and `continue` past one expectation, which
        # protected that loop and nothing else - the OBLIGATIONS pass further down
        # is a separate walk over the same expectations, and it died on a
        # `decision_detail` that was a string. Guarding one consumer of malformed
        # input is the same mistake as fixing one site of a claim: the input is
        # malformed for every reader, so it is refused once, here, before any
        # reader sees it.
        malformed = [m for i, exp in enumerate(case.get("expect", []))
                     for m in malformed_list_failures(f"{name}[{i}]", exp,
                                                      UNAVAILABLE_FIELD)]
        for msg in malformed:
            check(False, msg)
        if malformed:
            continue

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
            # EVERY declared list on this expectation, including the two that
            # were never asked - `evidence_surviving` and the unavailable-inputs
            # list are records a mapper writes, and both were consumed only
            # through `set()`.
            for _field in ("frm", "to", "applicable_rules", "licensed_by",
                           "evidence_surviving", UNAVAILABLE_FIELD):
                bad = repeats_failure(f"{where}: `{_field}`", exp.get(_field))
                check(not bad, bad or "")
            claimed_a.update(frm)
            claimed_b.update(to)
            # A LICENSED RULE'S PAIR PROPERTIES MUST ACTUALLY HOLD. The negative
            # witnesses pin a kind by making it FAIL; nothing made one hold, so
            # the senior definition could be rewritten in ways no case objected
            # to - `same_rule_message` extended with `start_line`, or
            # `anchored_content` replaced by it outright. Both were reported and
            # both were green, because every negative witness already differs on
            # rule or message and the positive cross-path cases happened to sit
            # at the same line on both sides.
            #
            # This reads the other direction: for a rule the case says licensed
            # the relation, every equality kind it requires - directly or through
            # its partner profile - has to hold between each predecessor and each
            # successor named. It decides no applicability; it takes the case's
            # own word for which rules applied and asks whether the payload
            # agrees, which is what the negative half already does.
            for rid_p in sorted(set(exp.get("licensed_by") or [])):
                if rid_p not in rules:
                    continue
                # BOTH TABLES. Intersecting with the equality map alone let
                # `line_drift` out: R-CONT-DRIFT could be licensed with the
                # successor on the predecessor's own line, the drift it requires
                # simply absent, and nothing here objected. An exclusion list
                # read as a filter and never as a thing needing its own reader.
                for kind_p in sorted(rule_needs(mapping_or_empty(rules[rid_p]))
                                     & (set(eq_fields_map) | set(df_fields_map))):
                    want_diff = kind_p in df_fields_map
                    fields_p = (df_fields_map if want_diff else eq_fields_map)[kind_p]
                    for a_p in frm:
                        for b_p in to:
                            oa_p = mapping_or_empty(by_id.get(a_p))
                            ob_p = mapping_or_empty(by_id.get(b_p))
                            wrong = sorted(f for f in fields_p
                                           if (oa_p.get(f) != ob_p.get(f)) != want_diff)
                            check(not wrong,
                                  f"{where}: {rid_p} licensed this relation and "
                                  f"requires {kind_p!r}, which `finding-lineage/v1` "
                                  f"says holds when {sorted(fields_p)} "
                                  f"{'differ' if want_diff else 'agree'} - and "
                                  f"{a_p} and {b_p} do not, on {wrong}. Either the "
                                  "case licenses a rule its own occurrences do not "
                                  "satisfy, or the kind has been redefined into "
                                  "something this relation was never meant to carry.")
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
            # `licensed_by` is a SET of surviving rules in the contract, and every
            # validation here normalised it through `set(lic)` - so a repeat passed
            # and the corpus sanctioned two raw shapes for one provenance record.
            # The uniqueness was checked for one field and not its twin, again.
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

            for rid, reason in mapping_or_empty(exp.get("not_applicable")).items():
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
                # A REFUSAL THAT NAMES NO PREDECESSOR CARRIES NO PAIR EVIDENCE. Both
                # `signals_defeated` and `evidence_surviving` are statements about a
                # RELATION - which signal was removed from it, which kinds survived in
                # it - and a b-side record has `frm: null`, so there is no pair for
                # either to be about. Three fixtures carried the a-side's defeat across
                # by symmetry, which recorded evidence about a relation the record does
                # not state. If the reason a b-side refusal happened ever needs the
                # candidates that were tried, that is a candidate-attempt trace and a
                # different shape, not this one.
                if exp.get("frm") is None:
                    for field in ("signals_defeated", "evidence_surviving"):
                        check(not exp.get(field),
                              f"{where}: names no predecessor and still carries "
                              f"{field}={exp.get(field)!r}. That is a claim about a pair "
                              "this record does not name; a defeat is why a relation signal "
                              "was removed, and there is no relation here to remove it from.")
                want, why_branch = mandated_reason(exp, policy["reason_mapping"], floor, senior,
                                   mapping_or_empty(policy.get("reason_selector"))
                                   .get("order"))
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
            # WHAT THE EXCLUSIONS DROPPED, ACROSS THE WHOLE EXPECTATION. The
            # stray-entry check used to live inside the exclusion branch, so an
            # expectation whose licensed rules exclude NOTHING carried any
            # `excluded_partners_reached_by` it liked, unread - the contract said
            # naming an undropped partner is rejected and the empty case was the
            # one nobody asked. Collected here, judged once, below.
            dropped_all: dict = {}
            for rid in lic:
                rule_r = rules[rid]
                binding = rule_r.get("record_binding")
                if binding is None and mapping_or_empty(rule_r.get("cardinality")).get("shape") == "1:1":
                    # At 1:1 there is exactly one occurrence in each role, so
                    # `every` and `at_least_one` are the SAME condition and the
                    # checker chooses no policy by applying it - see
                    # `record_binding_vocabulary.at_one_to_one`.
                    # ...and `single_entry`, because at one occurrence per role
                    # there is one pair to relate and no union to take.
                    binding = {"predecessor": {"quantifier": "every"},
                               "successor": {"quantifier": "every"},
                               "coverage": "single_entry"}
                if not binding:
                    continue
                for kind in list_or_empty(rule_r.get("requires_all")):
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
                    for role in SUBJECT_ROLES:
                        spec_r = mapping_or_empty(binding.get(role))
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
                            # WHAT THE EXCLUSION ASSUMES, ASKED OF THE MAPPING.
                            # The token's whole justification is that a partner at
                            # the predecessor's own path "is where the occurrence
                            # already was, so a continued rule reaches it and this
                            # record does not have to". That is a CLAIM ABOUT THE
                            # MAPPING, and nothing asked it: an occurrence at the
                            # predecessor's path whose enclosing symbol changed is
                            # reached by no continued rule at all, and the exclusion
                            # still lifted the record requirement off it - leaving it
                            # absorbed into the branch by `same_rule_message` and
                            # `anchored_content`, which any unrelated occurrence of
                            # that defect anywhere in the tree also shows.
                            #
                            # Only when the exclusion REMOVED someone. Where no
                            # partner sits at the predecessor's path it lifts nothing
                            # and assumes nothing, and demanding a continued rule
                            # there would reject `a-copy-into-two-new-files-is-a-branch`.
                            dropped = [o for o in (frm if role == "predecessor" else to)
                                       if o not in pool]
                            excl_spec = mapping_or_empty(
                                axes["excluding"].get(spec_r["excluding"]))
                            want_out = excl_spec.get("requires_applicable_outcome")
                            for o_ in dropped:
                                dropped_all.setdefault(o_, (rid, role, want_out))
                            if dropped and want_out:
                                # PER PARTNER, and that is the whole difference.
                                # The first form of this check asked only whether
                                # SOME applicable rule concluded the outcome, and
                                # one such rule then discharged the promise for
                                # every dropped partner at once: a second same-path
                                # successor with a different enclosing symbol rode
                                # in on the first one's rescuer, reached by nothing
                                # itself. Membership standing in for the correct
                                # member - the sub-form this branch has now found
                                # more times than any other, written into the fix
                                # for the previous instance of it.
                                rescue = mapping_or_empty(
                                    exp.get("excluded_partners_reached_by"))
                                for o_ in dropped:
                                    named = rescue.get(o_)
                                    check(isinstance(named, str)
                                          and mapping_or_empty(rules.get(named)).get(
                                              "outcome") == want_out
                                          and named in app,
                                          f"{where}: {rid} excludes "
                                          f"{shown_ids([o_], by_id)[0]!r} from the "
                                          "record's coverage because it sits at the "
                                          "predecessor's path, and "
                                          "`excluded_partners_reached_by` names "
                                          f"{named!r} for it - which has to be a rule "
                                          f"this mapping declares applicable AND that "
                                          f"concludes {want_out!r}. The exclusion lifts "
                                          "the record requirement on the promise that "
                                          "another rule carries THIS partner; a rule "
                                          "that carries a different one carries "
                                          "nothing here.")
                        pools[role] = pool

                    def shown(ids_):
                        return [by_id.get(o, {}).get("enclosing_symbol")
                                or by_id.get(o, {}).get("path") for o in ids_]
                    rels = [related_by(e, pairs, pools["predecessor"],
                                       pools["successor"], by_id) for e in entries]
                    # HOW THE ENTRIES COMBINE. This used to be `any(...)` for every
                    # rule, which is `single_entry` chosen by the checker and named
                    # nowhere. It made `every` unsatisfiable on a 1:N copy - git
                    # writes one record per destination - so the copy rule was left
                    # at `at_least_one`, and `at_least_one` licensed a branch over a
                    # successor no record named.
                    coverage = mapping_or_empty(binding).get("coverage")
                    # WHAT THE DISCRIMINATION SWEEP NEEDS, taken from the real
                    # evaluation rather than rebuilt later from the fixture.
                    coverage_inputs.setdefault((name, rid), []).append(
                        (binding, pools, entries, pairs, by_id))
                    if coverage == "union_of_entries":
                        held, how = coverage_holds(coverage, binding, pools, rels), (
                            f"and the records of {read_field} do not TOGETHER relate "
                            "this mapping as its `record_binding` requires. Under "
                            "`union_of_entries` every partner the quantifier ranges "
                            "over has to be named by some record; one that is named "
                            "by none of them is not part of this transformation.")
                    elif coverage == "single_entry":
                        held, how = coverage_holds(coverage, binding, pools, rels), (
                            f"and no SINGLE entry of {read_field} relates this mapping "
                            "as its `record_binding` requires. Two records describing "
                            "two transformations do not add up to one transformation.")
                    else:
                        held, how = False, (
                            f"and its `record_binding` declares coverage "
                            f"{coverage!r}, so there is no reading of {read_field} to "
                            "apply. An unreadable binding checks nothing, which is "
                            "worse than a wrong one.")
                    check(held,
                          f"{where}: {rid} rests on {sig!r}, {how} "
                          f"Predecessors {shown(pools['predecessor'])!r}, "
                          f"successors {shown(pools['successor'])!r}; the records hold "
                          f"{entries!r}.")

            # THE RESCUE MAP, JUDGED AGAINST EVERY EXCLUSION THIS EXPECTATION MADE
            # - the empty case included. `an-edit-elsewhere-is-still-the-same-defect`
            # excludes nobody and accepted `{"occ-nobody": "R-MERGE-FOLD"}` in
            # silence, because the only reader of the field ran inside a branch
            # that case never entered.
            rescue_all = mapping_or_empty(exp.get("excluded_partners_reached_by"))
            # ABSENT, not empty. The diagnostic below says the field "may not
            # appear at all" where nothing was dropped, and `{}` satisfied the
            # stray check because both sets were empty - the message claiming more
            # than the code, one line above the code. Two conforming mappers would
            # then disagree about whether to write the key.
            check(not (not dropped_all and "excluded_partners_reached_by" in exp),
                  f"{where}: no exclusion in this expectation dropped anybody, and it "
                  "still carries `excluded_partners_reached_by`. An empty map and an "
                  "absent one would be two spellings of the same fact, and a record "
                  "field with two spellings is one a reader has to test twice.")
            stray = sorted(set(rescue_all) - set(dropped_all))
            check(not stray,
                  f"{where}: `excluded_partners_reached_by` names {stray}, which no "
                  "exclusion in this expectation dropped. The field records who an "
                  "exclusion dropped and who catches them; naming anyone else "
                  "describes a rescue nothing needed - and an expectation that "
                  "excludes NOBODY may not carry the field at all.")
            # ONE 1:1 RESCUER CANNOT CATCH TWO PARTNERS. The map was checked
            # partner by partner, and each entry only for the rule's id, outcome
            # and membership in `applicable_rules` - so the SAME rescuer answered
            # for every dropped partner, and a second same-path successor with a
            # changed enclosing symbol rode in on the first one's. Both reviewers
            # found this independently, on the fix for the round before.
            #
            # What is checkable WITHOUT this suite becoming a second mapper is the
            # SHAPE: a rule whose cardinality relates one occurrence in a role
            # cannot relate two of them in one mapping. Two candidates satisfying a
            # 1:1 rule is `arbitration.multiplicity` - an ambiguity, not two
            # rescues. See `excluded_partners_rescuer_rule` for what this still does
            # NOT establish.
            per_rescuer: dict = {}
            for partner, named in sorted(rescue_all.items()):
                if isinstance(named, str) and partner in dropped_all:
                    per_rescuer.setdefault(named, []).append(partner)
            for named, partners in sorted(per_rescuer.items()):
                shape = str(mapping_or_empty(
                    mapping_or_empty(rules.get(named)).get("cardinality")).get("shape"))
                role = dropped_all[partners[0]][1]
                side = shape.partition(":")[0 if role == "predecessor" else 2]
                if side == "1" and len(partners) > 1:
                    check(False,
                          f"{where}: `excluded_partners_reached_by` names {named!r} as "
                          f"the rescuer of {sorted(partners)} - {len(partners)} "
                          f"partners in the {role} role - and {named} declares "
                          f"cardinality {shape!r}, which relates ONE. A 1:1 rule "
                          "reaching two occurrences of this mapping is an ambiguity "
                          "under `arbitration.multiplicity`, not two rescues; one of "
                          "them is being absorbed on a rescuer that cannot have "
                          "reached it.")

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
                for kind in list_or_empty(rules[rid].get("requires_all")):
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
            for signal, source in mapping_or_empty(exp.get("signals_defeated")).items():
                spec = policy["signal_defeaters"].get(signal)
                check(spec is not None,
                      f"{where}: {signal!r} is not a defeatable signal in the policy")
                if spec is None:
                    continue
                check(spec["defeated_by_signal"] == source or
                      mapping_or_empty(catalog.get(spec["defeated_by_signal"]))
                      .get("observable_from", "")
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
                cleared = clears_floor(surviving, senior, floor)
                if reason == lim.get("insufficient-evidence-kind"):
                    check(not cleared,
                          f"{where}: claims insufficient KINDS, but {sorted(set(surviving))} "
                          f"clears the floor of {floor} - by count, or because one of them "
                          "is `sufficient_alone`. The kinds are ample; it is the "
                          "combination that no rule accepts.")
                if reason == lim.get("insufficient-evidence-combination"):
                    check(cleared,
                          f"{where}: claims insufficient COMBINATION, but "
                          f"{sorted(set(surviving))} does not clear the floor of {floor}. "
                          "Below the floor the shortage really is of kinds.")

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
                        card = mapping_or_empty(rules[rid].get("cardinality"))
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
                bad = repeats_failure(f"{where}: decision_detail.{field}",
                                      detail.get(field))
                check(not bad, bad or "")
            for _rid, _ids in mapping_or_empty(detail.get("ambiguous_candidates")).items():
                bad = repeats_failure(f"{where}: ambiguous_candidates[{_rid!r}]", _ids)
                check(not bad, bad or "")

            cand = detail.get("ambiguous_candidates")
            blunted_ids = detail.get("rules_without_a_unique_candidate") or []
            if blunted_ids or cand:
                check(isinstance(cand, dict) and set(cand) == set(blunted_ids),
                      f"{where}: decision_detail.ambiguous_candidates must name the "
                      "candidates for exactly the rules recorded in "
                      f"rules_without_a_unique_candidate {sorted(blunted_ids)}, got "
                      f"{sorted(cand or {})}")
            for rid, ids_ in mapping_or_empty(cand).items():
                check(rid in rules, f"{where}: ambiguous_candidates names unknown rule {rid!r}")
                check(isinstance(ids_, list) and len(set(ids_)) >= 2,
                      f"{where}: {rid} is recorded as unable to choose between "
                      f"{ids_!r}; fewer than two candidates is not an ambiguity")
                # ONE REVISION PER LIST. `in occ_a or in occ_b` accepted a list
                # mixing both, which is not an ambiguity at all: candidates are
                # the alternatives a rule could not choose BETWEEN, and two
                # occurrences from different runs are endpoints of a mapping
                # rather than rivals for one end of it. A consumer reading such a
                # record cannot tell whether the rule failed to pick predecessors
                # or successors - the provenance says less than it appears to.
                sides = {("A" if oid in occ_a else "B") for oid in ids_ or []
                         if oid in occ_a or oid in occ_b}
                check(len(sides) <= 1,
                      f"{where}: ambiguous_candidates[{rid!r}] = {ids_!r} draws from "
                      "BOTH revisions. A rule that could not choose was choosing among "
                      "candidates on one side; a list spanning both records no "
                      "answerable question.")
                for oid in ids_ or []:
                    check(oid in occ_a or oid in occ_b,
                          f"{where}: candidate {oid!r} is in neither revision")

            overlap = (set(detail.get("rules_without_a_unique_candidate") or [])
                       & set(detail.get("rules_excluded_by_cardinality") or []))
            check(not overlap,
                  f"{where}: {sorted(overlap)} recorded as BOTH unable to choose and "
                  "excluded by cardinality. A rule lost at one stage, and the two "
                  "answer different questions when the rule is later changed.")

            # THE CONVERSE, which nothing asked. The loop below validates a
            # DECLARED defeat; nothing ever required one. A boundary whose
            # evidence revision B carries, and which applies to an occurrence
            # this expectation names, has to be either HONOURED - concluded as
            # the outcome it `proves` - or DEFEATED in writing. Deleting
            # `boundary_defeated` from `copy-at-one-to-one-is-not-a-branch` left
            # the suite green and the case stopped being adversarial:
            # `deleted_paths` earns `ended` for that predecessor unless the copy
            # record defeats it, and with the record gone it was an ordinary
            # copy-continuation wearing the name of a harder case. Review found
            # that one; the census here found a second, where the fold's
            # `removed_symbols` boundary had never been declared defeated at all.
            #
            # Derived, not listed: every boundary kind declares `match`,
            # `observable_from` and what it `proves`, so which boundaries applied
            # to which occurrence is read off the senior contract and the records
            # the fixture carries. No applicability is computed.
            declared_defeats = set(exp.get("boundary_defeated") or {})
            for bspec in senior["boundary_evidence_kinds"].values():
                _, hit = boundary_hits(bspec, frm, to, by_id, rev_b)
                if not hit or outcome == bspec.get("proves"):
                    continue
                check(bspec["value"] in declared_defeats,
                      f"{where}: {bspec['observable_from']} names "
                      f"{hit!r}, so {bspec['value']!r} "
                      f"applies to {hit!r} and proves {bspec.get('proves')!r} - but "
                      f"this expectation concludes {outcome!r} and records no defeat. "
                      "Boundary evidence carried and not honoured has to be defeated "
                      "in writing; silence is the absence-of-record defect this "
                      "contract exists to forbid.")

            # REVISION-LEVEL, so every decision about the pair records it.
            # `unavailable_inputs` means a signal that "could not be EVALUATED at
            # all ... for the revision" and is observed from
            # `revision_b.unavailable_signals`; `record_additions` says the field
            # is "Present whenever any were". The only check was the per-CASE
            # obligation, satisfied by whichever expectation happened to carry
            # it, so the mirror expectation could drop the record and stay green -
            # one stored refusal missing the machine-readable reason its twin
            # gives for the same revision pair.
            revision_unavailable = set(collect(rev_b, unavailable_from))
            if revision_unavailable:
                check(set(exp.get(UNAVAILABLE_FIELD) or []) == revision_unavailable,
                      f"{where}: {unavailable_from} declares "
                      f"{sorted(revision_unavailable)} unevaluable for the REVISION, "
                      f"so every decision about it records them; this one records "
                      f"{sorted(set(exp.get(UNAVAILABLE_FIELD) or []))}.")

            for kind, defeater in mapping_or_empty(exp.get("boundary_defeated")).items():
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
                role, hit = boundary_hits(spec, frm, to, by_id, rev_b)
                check(bool(hit),
                      f"{where}: {kind!r} matches on {spec['match']} and "
                      f"{spec['observable_from']} holds "
                      f"{sorted(collect(rev_b, spec['observable_from']))!r}, which names "
                      f"no {role} this expectation declares. The boundary never applied "
                      "here, so defeating it proves nothing.")
                # AND THE RECORD MUST NAME THE OCCURRENCE IT DEFEATS. Both bots
                # found this independently, and they were right: "the record is
                # carried" and "the boundary applied" were both checked, and
                # nothing ever asked whether the record was about the SAME
                # occurrence. A copy of an unrelated file, or a rename of one, is
                # an allowed defeater path and a non-empty collection, so it
                # satisfied every test here while explaining nothing about the
                # predecessor whose file was deleted.
                #
                # This is the discipline the rule bindings and the signal defeats
                # already keep - "no SINGLE entry relates this mapping", "a defeat
                # must be carried AND name these occurrences" - and the boundary
                # path was the one place it was never asked. A record cited where
                # it was named and never asked of the site next to it.
                # STRINGS ONLY, and not a `set` of whatever the records hold.
                # `collect` returns raw values, so a record whose `from` is an
                # object made `set(...)` raise TypeError: unhashable - the ninth
                # time on this branch that a guard has died on the malformed
                # input it exists to examine, and this one was written in the
                # same commit that quotes the other eight. A non-string record
                # value is a real violation, and it belongs to
                # `entry_shape_failures`, which reports it by name; this check
                # compares paths and symbols, so it looks at the values that are
                # paths and symbols.
                defeating = {v for v in collect(rev_b, defeater) if isinstance(v, str)}
                attr = str(spec["match"]).partition(".")[2]
                relieved = sorted(oid for oid in hit
                                  if by_id.get(oid, {}).get(attr) in defeating)
                check(bool(relieved) or not hit,
                      f"{where}: {defeater} holds {sorted(defeating)!r}, none of which "
                      f"names the {attr} of any occurrence {kind!r} applied to "
                      f"({sorted(by_id.get(o, {}).get(attr) for o in hit)!r}). An allowed "
                      "record about somebody else is not a defeat; it is the boundary "
                      "standing undisturbed while the fixture says otherwise.")

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
        # The last declared list `repeats_failure` did not reach. A duty written
        # twice is checked twice and means once; the verdict is unaffected, which
        # is exactly why it sat here after the sweep that added the predicate.
        bad = repeats_failure(f"{name}: case_obligations", duties)
        check(not bad, bad or "")
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
                elif duty == "required_kind_withheld_a_rule":
                    # A rule that did NOT apply because a kind its `requires_all`
                    # names failed to hold - and `not_applicable` has to say which
                    # kind, by its senior name. Written for R-CONT-DRIFT gaining
                    # `same_pattern_id`: the value that decides the case must be
                    # preregistered as the reason the rule stood down, not left as
                    # an assertion in this file.
                    # THE WITNESS IS NAMED, not searched for. Asking whether SOME
                    # rule mentioned SOME kind it requires is satisfied by any
                    # case - rules stand down naming their requirements all the
                    # time - so the obligation written to pin E's decision passed
                    # with R-CONT-DRIFT's entry saying nothing about
                    # `same_pattern_id`. See `required_kind_witnesses`.
                    spec_w = mapping_or_empty(
                        mapping_or_empty(policy.get("required_kind_witnesses")).get(name))
                    w_rule, w_kind = spec_w.get("rule"), spec_w.get("kind")
                    check(isinstance(w_rule, str) and w_rule in rules
                          and isinstance(w_kind, str),
                          f"{name}: carries `required_kind_withheld_a_rule` and "
                          f"`required_kind_witnesses` names {spec_w or None!r}. The rule "
                          "and the kind the case turns on are declared in the contract, "
                          "not looked for here.")
                    if (isinstance(w_rule, str) and w_rule in rules
                            and isinstance(w_kind, str)):
                        check(w_kind in rule_needs(rules[w_rule]),
                              f"{name}: the witness names {w_kind!r}, which "
                              f"{w_rule} does not require. A rule cannot stand down "
                              "over a requirement it does not have.")
                        # AND THE KIND HAS TO FAIL IN THIS CASE'S OWN PAYLOAD.
                        # Naming the rule and the kind pinned the DECLARATION and
                        # nothing else, so the same-site witness could be rewritten
                        # to carry one pattern id on both sides - `same_pattern_id`
                        # holding - while still declaring that R-CONT-SAME-SITE
                        # stood down because it did not. The claim the case exists
                        # to make, contradicted by the case, accepted. The two
                        # cross-path witnesses survived only because recomputing
                        # `pattern_id` caught the edit, which is luck, not a check.
                        # `pair_property_equality_fields` says which kinds are
                        # readable from a pair of occurrences - two strings the
                        # producer emitted, compared - and every witness kind must
                        # be one, so the table cannot be emptied into a vacuum. It
                        # lives in the SENIOR contract: a junior defining what a
                        # senior kind compares has redefined the kind, and the
                        # junior copy could be widened with `path` until a witness
                        # whose rule and message AGREED still read as the kind
                        # failing.
                        fields_w = (eq_fields_map.get(w_kind)
                                    or df_fields_map.get(w_kind))
                        check(isinstance(fields_w, list) and fields_w
                              and all(isinstance(f, str) for f in fields_w),
                              f"{name}: the witness names {w_kind!r}, and "
                              "`finding-lineage/v1.pair_property_fields` gives it "
                              f"{fields_w!r}. A witness whose kind cannot be read "
                              "off the pair is a claim this corpus cannot falsify.")
                        if isinstance(fields_w, list) and all(
                                isinstance(f, str) for f in fields_w) and fields_w:
                            preds = exp.get("frm")
                            preds = ([preds] if isinstance(preds, str)
                                     else list(preds or []))
                            # An equality holds when its fields AGREE; a
                            # difference holds when they all DIFFER. Reading only
                            # the first is what left `line_drift` unread.
                            diff_w = w_kind in df_fields_map
                            held = sorted(
                                (a_id, b_occ.get("occurrence_id"))
                                for a_id in preds
                                for b_occ in (case.get("revision_b") or {}).get(
                                    "occurrences") or []
                                if isinstance(b_occ, dict)
                                and by_id.get(a_id) is not None
                                and all((by_id[a_id].get(f) != b_occ.get(f)) == diff_w
                                        for f in fields_w))
                            check(not held,
                                  f"{name}: the witness says {w_rule} stood down "
                                  f"because {w_kind!r} did not hold, and it HOLDS for "
                                  f"{held} - the pair agrees on {fields_w}. A case "
                                  "that contradicts the claim it was preregistered to "
                                  "make proves the opposite of what it was written "
                                  "for.")
                        said = mapping_or_empty(exp.get("not_applicable")).get(w_rule)
                        if isinstance(said, str) and w_kind in said:
                            met = True
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
                        card = mapping_or_empty(mapping_or_empty(rules.get(rid))
                                                .get("cardinality"))
                        nf, nt = len(as_list(exp.get("frm"))), len(as_list(exp.get("to")))
                        blocked = (card.get("min_successors", 0) > nt
                                   or card.get("min_predecessors", 0) > nf)
                        check(blocked,
                              f"{name}: {rid} is claimed excluded by cardinality, but "
                              f"{card} does not rule out a {nf}:{nt} shape. The guard has "
                              "to do the excluding, not the note.")
                        # AND THE RULE HAS TO HAVE MATCHED SOMETHING. "Excluded by
                        # cardinality" means it matched its record and then met a
                        # shape it does not govern - so the record must be there.
                        # Deleting `revision_b.merged_symbols` from
                        # `an-ambiguity-outranks-a-cardinality-rejection` left the
                        # suite green: the case asserted a rule was considered and
                        # the thing it was considered on was gone. The same
                        # question is already asked of LICENSED rules one loop
                        # over; this is it asked of the adjacent site.
                        for kind_c in list_or_empty(mapping_or_empty(rules.get(rid))
                                                    .get("requires_all")):
                            sig_c = (kind_c if kind_c in catalog
                                     else kind_records.get(kind_c))
                            cat_c = catalog.get(sig_c)
                            if not cat_c:
                                continue
                            read_c, entries_c, pairs_c = catalog_read(cat_c, rev_b)
                            # ...and an entry that NAMES something. `from: []`
                            # left a fold record present and relating nobody, so
                            # "it matched" was satisfied by a record with no
                            # sources in it. Shape present, content vacuous - the
                            # same reading that let a prose field be emptied.
                            entries_c = [e for e in entries_c
                                         if isinstance(e, dict) and all(
                                             e.get(k) for k, _, _ in pairs_c)]
                            check(bool(entries_c),
                                  f"{name}: {rid} is recorded as excluded by "
                                  f"cardinality, which says it MATCHED {sig_c!r} and "
                                  f"then met the wrong shape - and {read_c} carries "
                                  "nothing. A rule excluded from a match it never had "
                                  "is a recall-set entry for a consideration that did "
                                  "not happen.")
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
    # EVERY BACKTICKED TOP-LEVEL KEY A PROSE BLOCK CITES HAS TO EXIST. I wrote
    # `what_the_suite_refuses_to_compute` into a new section this round - a
    # section whose whole subject is a claim nothing checks - and the key it
    # names has never existed. A cross-reference to nothing is the same defect as
    # a declaration nothing reads, and cheaper to catch.
    # THE NAMES THIS CONTRACT DEFINES, from everywhere it defines them - not
    # top-level keys alone. The first form of this check knew only top-level keys
    # and flagged `rule_licensed_alone`, which is a real case obligation: a
    # cross-reference gate that does not know the vocabulary it polices is worse
    # than none, because it teaches the next reader to silence it.
    # EVERY KEY EITHER CONTRACT CARRIES, AT ANY DEPTH - not the top level. The
    # first form of this gate read `set(policy)` and scanned only direct string
    # entries of top-level LIST-valued sections, so `rules.*.why`,
    # `record_binding_vocabulary.excluding.*.why` and every object-valued section
    # went unread; and its regex demanded two underscores, so `missing_reference`
    # walked through the part it did read. A gate covering part of what its own
    # declaration claims - written, this time, into the gate whose entire subject
    # is claims nothing checks. Both reviewers found it independently.
    def every_key(value) -> set:
        out: set = set()
        if isinstance(value, dict):
            for key, item in value.items():
                out.add(key)
                out |= every_key(item)
        elif isinstance(value, list):
            for item in value:
                out |= every_key(item)
        return out

    def string_leaves(value, trail=()):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from string_leaves(item, trail + (str(key),))
        elif isinstance(value, list):
            for pos, item in enumerate(value):
                yield from string_leaves(item, trail + (str(pos),))
        elif isinstance(value, str):
            yield ".".join(trail), value

    # A PROSE LIST HOLDS PROSE. This walk SKIPS anything that is not a string, so
    # a paragraph with a hole in it reads as a shorter paragraph - and one
    # arrived: `case_obligations.why[3]` was an empty list in the commit before
    # this, where a sentence carrying a `not_applicable` reference had been. My
    # own contract census put it there when a timeout killed it mid-run, and I
    # committed it because I read `git diff --stat` instead of the diff. The gate
    # that walks this prose could not see the hole, because a hole is not a
    # string. Reported by review, not by anything here.
    #
    # Every entry of a top-level list of strings must be a string: if the first
    # entry is prose, they all are. That is narrow on purpose - `preregistered_cases`
    # and `retired_names` are lists of names, and `deliberately_unresolved_conflicts`
    # is a list of objects, and none of them should be dragged into a rule about
    # paragraphs.
    # AT ANY DEPTH. The first form of this ran over top-level sections only - and
    # the hole it was written for is at `case_obligations.why`, one level down,
    # so it would have shipped without catching the defect it cites. Sixteenth
    # time on this branch that a check has covered part of what its own message
    # claims, and the second time inside a check written about exactly that.
    # PROSE IS IDENTIFIED BY THE FIELD'S NAME, NEVER BY WHAT IS CURRENTLY IN IT.
    # Two earlier drafts asked the contents: the first whether `value[0]` was a
    # string, the second whether ANY entry was. Both are defeated by emptying the
    # field - `case_obligations.why = []` or `notes = [[]]` erases a whole section
    # and stops it looking like prose at all, so the guard written for exactly that
    # field reported nothing. Both reviewers found it, independently, and both
    # named the same remedy: classify the field, do not interrogate its contents.
    #
    # A prose-named key must be a string, or a NON-EMPTY list of strings. Nothing
    # else, and emptiness is a failure rather than a way out.
    def prose_named(key: str) -> bool:
        return key in ("why", "notes", "note") or bool(
            re.search(r"_(why|note|notes|rule)$", key)) or key == "rule"

    # `*_rule` is the one ambiguous suffix: this contract uses it for prose AND
    # for two machine-readable declarations. They are named here rather than
    # inferred, and the naming is itself checked below - an exception list that
    # could quietly cover a prose field would be the hole one level up.
    STRUCTURED_PROSE_NAMED = {
        "eligibility.is_not_a_rule": bool,
        "arbitration.licensed_by_rule": dict,
    }

    def prose_faults(value, trail=()):
        out = []
        if isinstance(value, dict):
            for key, item in value.items():
                here = ".".join(trail + (str(key),))
                if prose_named(str(key)) and here not in STRUCTURED_PROSE_NAMED:
                    # AND IT HAS TO SAY SOMETHING. Type and length were the whole
                    # test, so `""` and `[""]` erased a section while keeping the
                    # shape the rule accepts - the fourth way to empty a prose
                    # field that this one check has now been shown to permit, and
                    # the fourth found by review rather than here. A shape is
                    # satisfiable vacuously; text is not.
                    #
                    # BLANK ENTRIES STAY LEGAL INSIDE A LIST: 53 of them across 16
                    # lists are paragraph separators. What is required is that
                    # SOME entry carries text.
                    if isinstance(item, str):
                        if not item.strip():
                            out.append((here, "is blank",
                                        "a prose field is text, and an empty "
                                        "string is the same erasure as a missing "
                                        "one with nothing to notice it by"))
                    elif not isinstance(item, list) or not item:
                        out.append((here, f"is {item!r}", "a prose field is a "
                                    "sentence or a non-empty list of them"))
                    else:
                        for pos, entry in enumerate(item):
                            if not isinstance(entry, str):
                                out.append((f"{here}[{pos}]", f"is {entry!r}",
                                            "every line of a paragraph is a line"))
                        if not any(isinstance(e, str) and e.strip() for e in item):
                            out.append((here, "holds no text",
                                        "blank entries are paragraph separators "
                                        "and some entry has to be a paragraph"))
                out += prose_faults(item, trail + (str(key),))
        elif isinstance(value, list):
            # AND THE CONTENT RULE, KEPT ALONGSIDE THE NAME RULE. They catch
            # different things and neither subsumes the other: the name rule sees
            # a prose field EMPTIED, which the content rule cannot; the content
            # rule sees a hole in any list of strings whatever its field is
            # called - `preregistered_cases`, `requires_all`, `forbids` - which
            # the name rule does not reach.
            #
            # Replacing the content rule with the name rule alone moved 335
            # mutations from clean failure to silent pass. The contract census
            # reported it BEFORE this was committed, which is the only reason it
            # is not the next round's finding.
            if any(isinstance(entry, str) for entry in value):
                for pos, entry in enumerate(value):
                    if not isinstance(entry, str):
                        out.append((f"{'.'.join(trail)}[{pos}]", f"is {entry!r}",
                                    "the other entries of that list are strings"))
            for pos, item in enumerate(value):
                out += prose_faults(item, trail + (str(pos),))
        return out

    for doc_name, doc in (("decision policy", policy), ("outcome contract", senior)):
        for where_, saw, why_ in prose_faults(doc):
            check(False,
                  f"the {doc_name}'s `{where_}` {saw}, and {why_}. A container where "
                  "a sentence belongs is a sentence deleted without anyone reading "
                  "the paragraph afterwards - which is how a `not_applicable` "
                  "reference went missing from `case_obligations.why` and was "
                  "committed. An EMPTY prose list is the same erasure with no "
                  "survivor to notice it by.")
    # THE EXCEPTION LIST, CHECKED. Each entry must exist and must really be the
    # structured kind claimed - otherwise a prose field could be exempted by
    # adding its path here, which is the hole this list would otherwise open.
    for path_, kind_ in sorted(STRUCTURED_PROSE_NAMED.items(), key=lambda kv: kv[0]):
        node = policy
        for seg in path_.split("."):
            node = mapping_or_empty(node).get(seg)
        check(isinstance(node, kind_),
              f"`{path_}` is exempt from the prose rule as a {kind_.__name__}, and it "
              f"is {type(node).__name__}. The exemption exists because two "
              "`*_rule` fields are machine-readable declarations, not paragraphs; an "
              "exemption that no longer describes its field is a prose field nobody "
              "is checking.")

    defined = every_key(policy) | every_key(senior)
    defined |= set(senior["evidence_kinds"]) | set(senior["outcomes"])
    # ...and the FIXTURE vocabulary, which the contract legitimately cites and
    # which lives in this suite's schema tables rather than in either document.
    for table in (EXPECTATION_KINDS, OCCURRENCE_KINDS, FIXTURE_KINDS, REVISION_KINDS,
                  DETAIL_KINDS, ELIGIBILITY_KINDS, ELIGIBILITY_FINDING_KINDS,
                  ELIGIBILITY_EXPECT_KINDS):
        defined |= set(table)
    defined |= {f.split(".")[-1] for f in (UNAVAILABLE_FIELD,)}
    # ...and the revision-B field names, which the contract defines through its
    # own catalog rather than as keys: `revision_b.merged_symbols` is where
    # `merged_symbols` is declared.
    specs = list(policy["structural_signals"].values()) + [policy["unavailable_inputs"]]
    specs += list(mapping_or_empty(senior.get("boundary_evidence_kinds")).values())
    for spec in specs:
        for read in (mapping_or_empty(spec).get("observable_from"),
                     mapping_or_empty(spec).get("defeated_by")):
            for one in str(read or "").replace("[]", "").split(","):
                defined |= {seg.strip() for seg in one.split(".") if seg.strip()}
    # STRINGS, CHECKED AND THEN USED. `set(list_or_empty(...))` raises on an
    # unhashable element - the fifteenth guard on this branch to die on the input
    # it exists to examine, added in the same change that closed the thirteenth
    # and fourteenth, and caught by the census rather than by reading it. The
    # census only sees it because it now sweeps scalar -> container, which is the
    # direction it was blind to until this round.
    for pos, name_ in enumerate(list_or_empty(policy.get("retired_names"))):
        check(isinstance(name_, str) and name_.strip(),
              f"`retired_names[{pos}]` is {name_!r}. Each entry is a name the "
              "contract mentions because it no longer exists; a container names "
              "nothing and cannot be compared against a citation.")
    defined |= {n_ for n_ in list_or_empty(policy.get("retired_names"))
                if isinstance(n_, str)}
    # ...and the selector's condition tokens, which the contract defines as VALUES
    # of a declared enumeration rather than as keys. Prose explaining why a branch
    # reads what it reads has to be able to name the branch.
    defined |= {mapping_or_empty(st).get("when")
                for st in list_or_empty(
                    mapping_or_empty(policy.get("reason_selector")).get("order"))
                if isinstance(mapping_or_empty(st).get("when"), str)}
    # WHOLE BACKTICKED SPANS, then segment by segment. Matching the identifier
    # pattern anywhere in the line found `excluded_by_cardinality` INSIDE
    # `decision_detail.rules_excluded_by_cardinality` - the gate inventing a
    # dangling reference out of a correct one, which would have been reported as
    # a contract defect and "fixed" by editing prose that was already right.
    for where_, line in string_leaves(policy):
        cited_names = set()
        for span in re.findall(r"`([a-z][A-Za-z0-9_.\[\]]*)`", line):
            for seg in span.replace("[]", "").split("."):
                if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", seg):
                    cited_names.add(seg)
        for cited in sorted(cited_names):
            check(cited in defined,
                  f"`{where_}` cites `{cited}`, which is not a name either contract "
                  "defines at any depth, nor a fixture field, nor a declared retired "
                  "name. A cross-reference to nothing reads as though something were "
                  "checking it - which is how `what_the_suite_refuses_to_compute` came "
                  "to be cited in a section whose whole subject is claims nothing "
                  "checks. A name the contract deliberately mentions because it NO "
                  "LONGER exists belongs in `retired_names`, where it is recorded "
                  "rather than merely tolerated.")

    for pair in sorted(({frozenset(c["between"]) for c in
                         policy["deliberately_unresolved_conflicts"]}), key=sorted):
        check(pair in exercised_refusals,
              f"the declared refusal {sorted(pair)} is exercised by no preregistered "
              "case. A conflict the contract deliberately refuses is a decision, and a "
              "decision with no case is frozen in name only.")

    # ---- 3c-bis. EVERY DECLARED `coverage` HAS TO MATTER. -------------------
    # A value the corpus cannot distinguish is a policy nobody chose. That is
    # exactly how `R-BRANCH-COPY` sat at `at_least_one` for twelve fixtures: no
    # case had two off-path successors, so the weaker reading was indistinguishable
    # from the stronger one and the weaker one licensed a branch over a successor
    # no record named. The contract said so in prose - "declared and not pinned" -
    # and the prose was where it stopped.
    #
    # The fold then repeated it one field over. `single_entry` was chosen, argued
    # for, and distinguished by NOTHING in the corpus: flipping it to
    # `union_of_entries` left all fourteen cases green, so two records naming one
    # source each would have been accepted as one fold against the contract's own
    # words. I reported that as a disclosed asymmetry instead of closing it, which
    # is the same move as the comment above - a reasoned-for exemption.
    #
    # So the law, and not the special case: for every rule that declares a
    # coverage, the declared value and some other value in the vocabulary must
    # DISAGREE on an input this suite actually evaluated. Where the corpus as
    # committed cannot separate them, the rule names a transform of a committed
    # case that can - `coverage_witness` - and the transform is applied here
    # rather than described.
    for rid in sorted(rules):
        binding_d = mapping_or_empty(rules[rid].get("record_binding"))
        declared = binding_d.get("coverage")
        if not declared:
            continue
        others = [v for v in sorted(axes["coverage"]) if v != declared]
        witness = mapping_or_empty(binding_d.get("coverage_witness"))
        wcase, wtransform = witness.get("case"), witness.get("transform")
        # STRINGS FIRST, because both are about to be used as dictionary keys.
        # `wtransform in COVERAGE_TRANSFORMS` raises TypeError on a list, and
        # `coverage_inputs.get((wcase, rid))` raises on an unhashable case - the
        # thirteenth and fourteenth guards on this branch to die on the input they
        # exist to examine, both introduced by the check that closed the twelfth.
        #
        # The fixture and contract censuses did not see these: both mutate
        # CONTAINERS INTO SCALARS and never the reverse, so a string field turning
        # into a list is a direction the instrument does not sweep. That is a gap
        # in the measurement, not only in the code.
        shape_bad = [f"{rid}.record_binding.coverage_witness.{field} is {value!r}, "
                     "not a string. It is used as a dictionary key, and an "
                     "unhashable one raises instead of reporting."
                     for field, value in (("case", wcase), ("transform", wtransform))
                     if not isinstance(value, str)]
        for msg in shape_bad:
            check(False, msg)
        if shape_bad:
            continue
        check(wtransform in COVERAGE_TRANSFORMS,
              f"{rid}.record_binding.coverage_witness names transform "
              f"{wtransform!r}; this suite can apply "
              f"{sorted(COVERAGE_TRANSFORMS)}. A witness it cannot run is a witness "
              "nobody hears.")
        # AND WHAT IT MUST CONCLUDE. Separation alone was the first draft of this
        # check and it did not catch the finding it was written for: flipping the
        # fold to `union_of_entries` left the witness still separating the two
        # readings, so the sweep passed a value the contract's own `why` rejects.
        # A law that proves two options are distinguishable says nothing about
        # which one was taken. The verdict is declared beside the value, in the
        # contract, and executed here.
        verdict = witness.get("verdict")
        check(verdict in ("accepts", "rejects"),
              f"{rid}.record_binding.coverage_witness declares verdict {verdict!r}, "
              "not 'accepts' or 'rejects'. Without it the witness shows only that the "
              "readings differ, which is true whichever one the rule picked.")
        recorded = coverage_inputs.get((wcase, rid))
        check(bool(recorded),
              f"{rid}.record_binding.coverage_witness names case {wcase!r}, and this "
              f"rule's binding was not evaluated on it. `coverage_inputs` holds "
              f"{sorted(k[0] for k in coverage_inputs if k[1] == rid)} for {rid}. A "
              "witness has to be a case where the binding actually ran.")
        if (wtransform not in COVERAGE_TRANSFORMS or not recorded
                or verdict not in ("accepts", "rejects")):
            continue
        separated, verdicts = set(), set()
        for binding_w, pools_w, entries_w, pairs_w, by_id_w in recorded:
            moved = COVERAGE_TRANSFORMS[wtransform](entries_w, pairs_w)
            rels_w = [related_by(e, pairs_w, pools_w["predecessor"],
                                 pools_w["successor"], by_id_w) for e in moved]
            mine = coverage_holds(declared, binding_w, pools_w, rels_w)
            verdicts.add(mine)
            for other in others:
                if coverage_holds(other, binding_w, pools_w, rels_w) != mine:
                    separated.add(other)
        check(separated == set(others),
              f"{rid} declares coverage {declared!r}, and on {wcase!r} under "
              f"transform {wtransform!r} it agrees with {sorted(set(others) - separated)} "
              "- so those readings are the same policy here and this rule chose "
              "between them on paper only. Either the witness does not separate "
              "them or the declaration is not load-bearing; both are a value nobody "
              "picked.")
        check(verdicts == {verdict == "accepts"},
              f"{rid} declares coverage {declared!r} and a witness that it "
              f"{verdict} {wcase!r} under {wtransform!r} - and it does not: the "
              f"reading concludes {sorted(verdicts)} where "
              f"{verdict == 'accepts'} was declared. Two records naming one partner "
              "each are two transformations or they are one; the contract says which, "
              "and this is where it either holds or is a sentence.")

    # ---- 3d. THE ELIGIBILITY CORPUS. ----------------------------------------
    # Stage 0 is answered before the relation problem is posed, so its cases live
    # in their own corpus and are shaped like the INPUT they refuse rather than
    # like an edge. `record_shape: input_local` is the whole point: a relation
    # record must reference its subject, and the reference it would use is the id
    # that is missing.
    elig = mapping_or_empty(policy.get("eligibility"))
    # THE STAGE'S OWN DECLARATIONS, BOUND. `record_shape`, `precedence` and
    # `forbids` were three tokens no check read - the shape this branch has found
    # a dozen times, written into the section that was being added to fix another
    # instance of it. Each is bound to the thing it describes rather than merely
    # spelled correctly.
    check(elig.get("record_shape") == "input_local",
          f"`eligibility.record_shape` is {elig.get('record_shape')!r}. The corpus "
          "encodes `input_local` mechanically - its expectation schema declares no "
          "`frm` and no `to`, and an undeclared key fails - so a different token here "
          "would describe a corpus that does not exist.")
    check(elig.get("is_not_a_rule") is True,
          "`eligibility.is_not_a_rule` must stay true: no rule id names this stage, "
          "and `rules` is what arbitration ranges over.")
    check(elig.get("precedence") == "before_every_other_stage",
          f"`eligibility.precedence` is {elig.get('precedence')!r}")
    first = (list_or_empty(policy.get("decision_procedure")) or [""])[0]
    check(first.strip().startswith("0. ELIGIBILITY"),
          f"`decision_procedure` opens with {first.strip()[:40]!r}. "
          "`eligibility.precedence` says this stage runs before every other, and the "
          "procedure is where that is either true or prose.")
    # `forbids`, BOUND TO FIELDS RATHER THAN READ AS PROSE. Each declared token
    # is one the suite carries a field vocabulary for, and the two sets must be
    # EQUAL in both directions: a token with no vocabulary is a sentence nothing
    # reads, and a vocabulary the contract stopped declaring is an enforcement
    # nobody agreed to.
    forbids = mapping_or_empty(elig.get("forbids"))
    check(isinstance(elig.get("forbids"), dict),
          f"`eligibility.forbids` is {type(elig.get('forbids')).__name__}, not an "
          "object of prohibition-token -> why. It was a list of sentences, and a "
          "list of sentences is what let all four be replaced by `['anything', "
          "'else']` with this suite still reporting OK.")
    check(sorted(forbids) == sorted(ELIGIBILITY_FORBIDDEN_FIELDS),
          f"`eligibility.forbids` declares {sorted(forbids)} and the suite can "
          f"enforce {sorted(ELIGIBILITY_FORBIDDEN_FIELDS)}. Undeclared-but-enforced "
          "is a rule nobody wrote down; declared-but-unenforceable is the prose this "
          "check exists to stop being.")
    check(isinstance(elig.get("forbids_rule"), str)
          and len(elig.get("forbids_rule", "").strip()) > 80,
          "`eligibility.forbids_rule` must state what the tokens are and why they "
          "are tokens; without it the next reader sees four identifiers and no "
          "reason they are not sentences again.")
    for token in sorted(set(forbids) & set(ELIGIBILITY_FORBIDDEN_FIELDS)):
        why = forbids[token]
        check(isinstance(why, str) and len(why.strip()) > 20,
              f"`eligibility.forbids.{token}` is {why!r}. The token is what the "
              "suite enforces; the value is what a human is owed for it.")
        for field in ELIGIBILITY_FORBIDDEN_FIELDS[token]:
            check(field not in ELIGIBILITY_EXPECT_KINDS,
                  f"`eligibility.forbids` declares {token!r}, and the eligibility "
                  f"expectation schema declares {field!r}. The schema is what a "
                  "fixture is allowed to say; a prohibition its own schema admits is "
                  "not a prohibition.")
    elig_forbidden = {f: t for t, fs in ELIGIBILITY_FORBIDDEN_FIELDS.items() for f in fs}

    elig_cases = list_or_empty(elig.get("preregistered_cases"))
    elig_on_disk = sorted(f[:-5] for f in os.listdir(ELIGDIR) if f.endswith(".json"))
    check(sorted(elig_cases) == elig_on_disk,
          f"`eligibility.preregistered_cases` is {sorted(elig_cases)} and the corpus on "
          f"disk is {elig_on_disk}. Same gate the relation matrix uses: a case nobody "
          "declared is a case nobody reviewed.")
    elig_sides = set()
    for cname in sorted(set(elig_cases) & set(elig_on_disk)):
        with open(os.path.join(ELIGDIR, f"{cname}.json"), encoding="utf-8") as fh:
            ecase = json.load(fh)
        where = f"eligibility/{cname}"
        bad = kind_table_failures(where, ecase, ELIGIBILITY_KINDS,
                                  frozenset(ELIGIBILITY_KINDS) - {"title"})
        for msg in bad:
            check(False, msg)
        if bad:
            continue
        check(ecase["case"] == cname, f"{where}: case field is {ecase['case']!r}")
        check(ecase["contract"] == "finding-lineage-decision/v1",
              f"{where}: wrong contract {ecase['contract']!r}")
        check(ecase["status"] == "preregistered-unimplemented",
              f"{where}: stays preregistered until a mapper exists")
        check(len(ecase["why"]) > 40, f"{where}: `why` must state what the case defends")
        check(ecase["revision"] in ("a", "b"),
              f"{where}: revision is {ecase['revision']!r}, not 'a' or 'b'")
        elig_sides.add(ecase["revision"])

        finding = ecase["finding"]
        fbad = kind_table_failures(f"{where}.finding", finding, ELIGIBILITY_FINDING_KINDS,
                                   frozenset(ELIGIBILITY_FINDING_KINDS))
        for msg in fbad:
            check(False, msg)
        if not fbad:
            check(finding["occurrence_id"] is None,
                  f"{where}: the finding declares occurrence_id "
                  f"{finding['occurrence_id']!r}. This corpus exists for the null case; "
                  "a case with an identity belongs in the relation matrix.")
            want = finding_pattern.pattern_id(finding["path"], finding["rule"],
                                              finding["message"])
            check(finding["pattern_id"] == want,
                  f"{where}: pattern_id is {finding['pattern_id']!r}, and "
                  f"`finding-pattern/v1` computes {want!r}. A finding with no "
                  "occurrence identity still has a PATTERN identity - that is the "
                  "distinction the two contracts exist to keep.")
            limits = list_or_empty(finding["identity_limitations"])
            check(bool(limits),
                  f"{where}: the finding records no `identity_limitations`. "
                  "`occurrence.py` never returns a null id without saying why, and a "
                  "fixture that omits the reason is not the record the mapper receives.")
            # THE REASON, AND THE RIGHT KIND OF REASON. `bool()` on the list was
            # the whole check, so `[{}]` and `[42]` passed it - a fixture saying
            # "there is a reason" without one. Same shape as `forbids` before it
            # became tokens, one field away.
            for index, limit in enumerate(limits):
                # `isinstance` FIRST. `limit in LIMITATION_VOCABULARY` raises
                # TypeError on an unhashable element - so the check written to
                # report a malformed limitation died on one, which is the tenth
                # time on this branch that a guard has crashed on the input it
                # exists to examine, and the second time in this one section.
                check(isinstance(limit, str) and limit in LIMITATION_VOCABULARY,
                      f"{where}: identity_limitations[{index}] is {limit!r}, which "
                      "`occurrence.py` does not emit. The fixture stands in for a "
                      "record that module produced; a token it never produces "
                      "describes an input the mapper will not receive.")
            # THE PRODUCER'S OWN ANSWER, asked of the finding as written. A
            # prefix test stood here - "at least one token blocks an id" - and it
            # passed a limitation set `resolve()` could not have produced for THIS
            # finding: both cases set `start_column: null` and neither declared
            # `physical-anchor-missing:start-column`, which `resolve()` appends
            # unconditionally in that case. The fixtures froze a record the
            # producer cannot emit, and a checker that reimplements the predicate
            # would only have frozen a second opinion about it.
            #
            # The two inputs `resolve()` takes that a normalized finding does not
            # carry - producer provenance and anchor ambiguity - are read OFF the
            # declared limitations, so the fixture still chooses its own scenario.
            # Everything derivable from the finding's own fields is then the
            # producer's to decide, and the answer has to match exactly.
            if limits and all(isinstance(x, str) for x in limits):
                phys = {"path": finding["path"], "start_line": finding["start_line"],
                        "start_column": finding["start_column"]}
                blind = finding_occurrence.LIMIT_NO_RUN_ID in limits
                got_id, got_limits = finding_occurrence.resolve(
                    finding["pattern_id"], phys,
                    None if blind else "preregistered-run",
                    None if blind else "preregistered-producer",
                    finding_occurrence.LIMIT_AMBIGUOUS_ANCHOR in limits)
                check(got_id is None,
                      f"{where}: `resolve()` returns {got_id!r} for this finding, not "
                      "None. The limitations it declares do not withhold an identity, "
                      "so the mapper would receive an identified finding and stage 0 "
                      "would never see it.")
                check(sorted(limits) == got_limits,
                      f"{where}: the finding declares {sorted(limits)} and `resolve()` "
                      f"returns {got_limits} for it. It returns EVERY applicable "
                      "limitation, not the first - so a set that differs from the "
                      "producer's is a record the producer cannot emit, whichever "
                      "direction it differs in.")

        exp = ecase["expect"]
        ebad = kind_table_failures(f"{where}.expect", exp, ELIGIBILITY_EXPECT_KINDS,
                                   frozenset(ELIGIBILITY_EXPECT_KINDS))
        for msg in ebad:
            check(False, msg)
        if ebad:
            continue
        check(exp["outcome"] == elig.get("outcome"),
              f"{where}: concludes {exp['outcome']!r}; `eligibility.outcome` is "
              f"{elig.get('outcome')!r}. The stage declares one answer and the corpus "
              "does not get a second opinion about it.")
        check(exp["reason"] == elig.get("reason"),
              f"{where}: names reason {exp['reason']!r}; `eligibility.reason` is "
              f"{elig.get('reason')!r}")
        check(exp["reason"] in senior_limitations,
              f"{where}: {exp['reason']!r} is not a limitation `finding-lineage/v1` "
              "declares. The junior layer may not invent one from below.")
        # ZERO RULES, ALL THREE STAGES. "No rule applied" is not the claim - the
        # claim is that no rule was ever MATCHED, because stage 0 absorbs before
        # matching happens. Checking only `licensed_by` would accept a fixture
        # that ran the whole procedure and then found nothing, which is a
        # different decision reached for a different reason.
        for field in ("matched_rules", "applicable_rules", "licensed_by"):
            check(exp[field] == [],
                  f"{where}: {field} is {exp[field]!r}. Stage 0 settles the answer "
                  "before any evidence is read, so every rule stage is empty - not "
                  "empty-because-nothing-fired, empty-because-nothing-ran.")
        # THE SAME PROHIBITION, ASKED OF THE FIXTURE. The kind table above
        # rejects undeclared keys, so this is a second reading of one fact - and
        # deliberately: the table can grow a field, and if it ever does, the
        # failure a reader gets should name the prohibition rather than report a
        # key nobody declared.
        for field in sorted(set(exp) & set(elig_forbidden)):
            check(False,
                  f"{where}.expect carries {field!r}, which `eligibility.forbids` "
                  f"rules out as {elig_forbidden[field]!r}. Stage 0 refuses BECAUSE "
                  "the identity is absent; an expectation that names one has answered "
                  "with the invention upstream declined to make.")
        exercised_reasons.add(exp["reason"])
        # THE SAME QUESTION THE RELATION CORPUS ASKS OF ITS OWN `forbid`, which
        # `fixture_shape_failures` answers element by element. Here it was
        # `bool()` alone: a list of five objects satisfied it, and `forbid`
        # states in words what the case must not conclude.
        check(bool(ecase["forbid"]), f"{where}: nothing is forbidden")
        for index, forbidden in enumerate(list_or_empty(ecase["forbid"])):
            check(isinstance(forbidden, str) and forbidden.strip(),
                  f"{where}.forbid[{index}] is {forbidden!r}. `forbid` states in "
                  "words what the case must NOT conclude; a container states "
                  "nothing.")

    check(elig_sides == {"a", "b"},
          f"the eligibility corpus covers sides {sorted(elig_sides)}. Both are needed: "
          "the a-side case is a predecessor that cannot be named and the b-side is a "
          "successor, and assuming one side covers the other has already been wrong "
          "once on this branch.")

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
    # THE DOC'S RULE TABLE IS WHAT A MAPPER IS BUILT FROM. Adding `same_pattern_id`
    # to R-CONT-DRIFT left that row saying the old three requirements, so the
    # frozen policy demanded a refusal while the documentation described the false
    # continuity the new case exists to forbid. Anyone implementing from the table
    # would have written the defect. Reported by review; the row is corrected and
    # the class is closed here rather than the instance.
    # THE REFUSAL TABLE IS THE OTHER FINITE SET THE DOC RESTATES. It listed six
    # reasons under a sentence saying "Five" - the sixth arrived with stage 0 and
    # the count was never updated - and nothing compared the table to the set the
    # policy can actually emit. Same shape as the rule table, one section down.
    emitted_short = {r.rsplit(":", 1)[-1] for r in emitted}
    tabled = {m for m in re.findall(r"^\| `([a-z][a-z-]+)` \|", doc, re.M)
              if m in {v.rsplit(":", 1)[-1] for v in senior["limitations"].values()}}
    check(tabled == emitted_short,
          f"the doc's refusal table names {sorted(tabled)} and this policy can emit "
          f"{sorted(emitted_short)}. The table is where a reader learns which "
          "refusals exist; a reason it omits is one nobody will handle, and one it "
          "invents is a value the policy never produces.")
    check(re.search(r"^Six, and all six are drawn from step 0", doc, re.M) is not None,
          "the refusal section must open by counting the refusals it lists, and the "
          "count must be six. It said `Five` while the table held six: the sentence "
          "was written before stage 0 added `missing-occurrence-id` and was never "
          "asked again.")

    for rid_d in sorted(rules):
        row = re.search(r"^\| `" + re.escape(rid_d) + r"` \|.*$", doc, re.M)
        check(row is not None,
              f"the doc's rule table has no row for {rid_d}. The table is the "
              "human-readable statement of what each rule requires; a rule missing "
              "from it is a rule nobody implementing from the document will write.")
        if row is None:
            continue
        # `rule_needs`, NOT `requires_all`. A group rule's per-partner profile is a
        # requirement of the same rule - `rule_needs` has said so since it was
        # written, and this file already calls it in three other places - and the
        # table presents both in one `requires` column. Reading only the direct
        # list let the R-BRANCH-COPY row drop `same_rule_message` and
        # `anchored_content` and stay green, describing a branch that needs only
        # its structural record. A mapper built from that row would accept any
        # successor the copy record named.
        # BOTH DIRECTIONS. Checking only contract -> doc left the contract free to
        # DROP a requirement: the row would then name one more than the rule, and
        # nothing noticed. That is why the reader audit found `requires_all`
        # unpinned on all three 1:1 rules whose first member is not a structural
        # record - removing `same_path` from R-CONT-SAME-SITE changed no verdict.
        # The table is a second declaration of the same finite set, so the honest
        # relation is equality.
        needs = {k for k in rule_needs(mapping_or_empty(rules[rid_d]))
                 if isinstance(k, str)}
        named = set(re.findall(r"`([a-z_]+)`", row.group(0)))
        absent = sorted(needs - named)
        extra = sorted(k for k in named - needs if k in senior["evidence_kinds"]
                       or k in policy["structural_signals"])
        check(not absent,
              f"the doc's row for {rid_d} does not name {absent}, which the rule "
              "requires. The contract and the table would then describe two "
              "different rules, and the table is the one a mapper is built from.")
        check(not extra,
              f"the doc's row for {rid_d} names {extra}, which the rule does NOT "
              "require. Either the row is stale or the contract quietly dropped a "
              "requirement - and a dropped requirement is a rule that licenses more "
              "than it was frozen to license.")
        rule_d = mapping_or_empty(rules[rid_d])
        check(f"`{rule_d.get('outcome')}`" in row.group(0),
              f"the doc's row for {rid_d} does not name its outcome "
              f"{rule_d.get('outcome')!r}. The outcome column is the same "
              "declaration as `rules.{rid}.outcome` and had no link to it.")
        # THE CARDINALITY CELL, EXACTLY, AND THE MINIMUM WITH IT. `shape_d in
        # row` was a substring test over the whole row, so the column was free to
        # say anything containing `1:N` - `1:N, N>=3` passed while the rule
        # declares `min_successors: 2`, and `11:N` would have passed too. The
        # minimum was the half nothing read: it is enforced against fixtures, and
        # the table restating it was restating it unchecked. The doc's rendering
        # is the shape plus `, N>=<min>` where a minimum is declared, and it is
        # compared against that rendering rather than searched for inside a line.
        card_d = mapping_or_empty(rule_d.get("cardinality"))
        want_card = str(card_d.get("shape")) + "".join(
            f", N>={card_d[k]}" for k in ("min_predecessors", "min_successors")
            if k in card_d)
        cells_d = [c.strip() for c in row.group(0).strip().strip("|").split("|")]
        said_card = cells_d[2] if len(cells_d) > 2 else None
        check(said_card == want_card,
              f"the doc's row for {rid_d} gives cardinality {said_card!r} and the "
              f"rule declares {want_card!r}. The column is a second statement of "
              "`cardinality`, and a mapper built from a table that relaxes the "
              "minimum would license a branch of one.")

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
