# Lineage decision policy — which evidence licenses which conclusion

**Status: contract frozen, implementation not started.** This is Own.NET#266
slice 2, step 1. There is still no mapper, and nothing in `aggregate/`,
`identity/pattern.py`, `identity/occurrence.py` or `runtime/` changes here.

Step 0 froze [`finding-lineage/v1`](../contracts/finding-lineage-v1.json): *what
a mapping may conclude*, and *what it must show* for the claim. It deliberately
left one question open, and said so — which combinations of evidence are enough.
That is what
[`finding-lineage-decision/v1`](../contracts/finding-lineage-decision-v1.json)
answers, and it is subordinate: where the two appear to disagree, the outcome
contract wins and this one is the thing that is wrong.

| | question | contract |
|---|---|---|
| step 0 | what may a mapping conclude, and what must it show? | `finding-lineage/v1` |
| step 1 | which evidence licenses which conclusion, and what happens when two answers apply at once? | `finding-lineage-decision/v1` |
| step 2+ | how is it computed? | *no mapper exists* |

## Four things that turned out to be load-bearing

Most of this document is those four. Each was found by trying to write something
down precisely and discovering the draft could not survive it.

### 1. Three sets, not one: match → filter → applicable → licensed

A mapping does not "find the rule that fits". It runs stages, and each stage's
output is recorded:

```
signals evaluated
  -> DEFEAT      remove signals an explaining record accounts for
  -> MATCH       every rule whose predicate holds; one or several candidates
  -> FILTER      uniqueness (1:1) and cardinality (1:N, N:1)
  -> applicable_rules
  -> ARBITRATE   dominance, refusals
  -> licensed_by
```

The distinction between MATCH and FILTER is the one that matters, and this file
had it wrong for a commit. A rule may match *several* candidate partners — that
is a fact about its predicate, not a defect. `R-CONT-DRIFT` does not ask about
content, so in a symbol holding two occurrences of one pattern it matches both.
It has therefore singled out nobody, and a 1:1 outcome requires exactly one
candidate. So it does not survive the filter, does not enter
`applicable_rules`, and does not reach arbitration — where it would otherwise
"disagree" with a rule that actually licensed something.

Uniqueness is checked **per rule**, not per outcome. In the same shape
`R-CONT-SAME-SITE` *does* ask about content and singles out one candidate. The
discriminating rule licenses; the blunt one is recorded as unable to choose.
Were uniqueness checked per outcome, the pair would collapse into ambiguity and
a real continuation would be thrown away.

**And the recall set is the union, not a field.** "Which mappings must I
revisit if I change this rule?" is answered by

```
recall = applicable_rules
       + decision_detail.rules_without_a_unique_candidate
       + any further explicitly recorded rejected stage
```

A rule dropped for matching two candidates is *exactly* a mapping that would
change if that rule were made more discriminating — and it is not in
`applicable_rules` at all. This is why a rejected stage is **recorded** rather
than computed and discarded: a stage whose output is thrown away cannot be
recalled from.

### 2. The floor is not the algorithm

Step 0 sets `minimum_evidence_kinds_for_continued = 2` and calls it a floor.
The temptation, when the structural rules turned out to need a per-partner
condition, was to write "at least two kinds". It is wrong, and the fixture that
proves it is `defeated-signal-drops-below-the-floor`:

- a formatter pass defeats `anchored_content`;
- **three** kinds survive — `same_path`, `same_pattern_id`,
  `structural_context` — comfortably above a floor of two;
- and no rule is satisfied, because no rule asks for that combination.

Two kinds is the minimum a mapping must clear. It never says any two suffice:
`same_path` plus `same_pattern_id` is two kinds and describes a twin, which is
the shape the whole contract exists to refuse. Choosing *which* combinations
license *what* is the job step 0 left to step 1, and answering it with a
cardinal number hands the job back.

That distinction now has its own vocabulary. The senior contract was amended to
carry both:

| reason | means |
|---|---|
| `insufficient-evidence-kind` | the floor was not cleared. The count is the problem. |
| `insufficient-evidence-combination` | the floor was cleared, sometimes comfortably, and no declared combination survives. |

Reporting the second as the first says the evidence was thin when it was ample
and simply did not add up to a rule anyone declared. The integrity suite checks
this mechanically: a case declaring a defeat must declare what survived, and
the `-kind` reason must sit below the floor while `-combination` must sit at or
above it.

### 3. Cardinality is a precondition, not a repair

Every rule declares its shape — `1:1` for the four continued rules, `1:N` with
`min_successors: 2` for the branch, `N:1` with `min_predecessors: 2` for the
fold — and a rule whose shape does not fit simply does not apply.

The alternative was to let a lone copy record license `branched` and have
`arbitration.multiplicity` overturn it a section later. That is one question
answered in two places, and the two places are a theological dispute between
halves of a JSON document waiting to be debugged at the worst possible moment.

The boundary is worth a case of its own, and has one. In
`copy-record-dominates-the-single-match` a copy record explains a *multiplicity*
and licenses `branched` over a perfectly good 1:1 match. In
`copy-at-one-to-one-is-not-a-branch` the same kind of record, with one
successor, explains a *move* — `R-BRANCH-COPY` is guarded out and `R-CONT-COPY`
answers. One record, two readings; cardinality chooses.

### 4. What the suite refuses to compute

`identity/tests/test_lineage_decision.py` never decides which rules a real
evidence record produces. That is **applicability**, it is domain reasoning, and
a checker doing it would be a second mapper — hidden, unversioned, and worse
dressed than the first.

So the work is split, and the split is the point:

| | who answers | how it is checked |
|---|---|---|
| *does this evidence produce that rule set?* | the fixtures, by declaring it | not computed by anything, yet |
| *given that rule set, what is the outcome?* | the arbitration algebra | mechanically, on every fixture |
| *is the algebra well-defined at all?* | a written proof | axioms checked on the real policy; the theorem falsified against a fixed model |

A fixture declares `applicable_rules`; the suite then requires its declared
outcome and `licensed_by` to equal what arbitrating that set yields. Fixture and
algebra may not describe two different policies — which is a real failure this
project shipped for one commit, when the contract demanded "exactly one rule
dominates every other" while the proof and the checker used surviving outcome
classes.

Everything else the suite checks is about records being **carried** rather than
asserted: a claimed defeat must be present in revision B *and name this
occurrence*, on the key the catalog says it matches on; a claimed unavailable
input must appear in the field the contract declares; a rule may not be
applicable while requiring a signal that was defeated or never evaluated.

## The rules

Six, deliberately small and deliberately not exhaustive.

| id | outcome | shape | requires |
|---|---|---|---|
| `R-CONT-SAME-SITE` | `continued` | 1:1 | `same_path`, `structural_context`, `anchored_content` |
| `R-CONT-DRIFT` | `continued` | 1:1 | `same_path`, `structural_context`, `line_drift` |
| `R-CONT-RENAME` | `continued` | 1:1 | `path_rename`, `structural_context`, `anchored_content` |
| `R-CONT-COPY` | `continued` | 1:1 | `copy_record`, `structural_context`, `anchored_content` |
| `R-BRANCH-COPY` | `branched` | 1:N, N>=2 | `copy_record` (group) + per successor: `same_pattern_id`, `anchored_content` |
| `R-MERGE-FOLD` | `merged` | N:1, N>=2 | `merge_record` (group) + per predecessor: `same_pattern_id`, `anchored_content` |

**No rule licenses `ended` or `new`.** Those are earned by boundary evidence,
which step 0 already governs; a rule for them here would create a second,
competing route to a death or a birth — the exact defect that contract was
corrected for.

**Rules cite IDs, never a confidence score.** A scalar collapses *which* signals
fired into a number, and then "would this mapping still be made under the new
rule?" stops having an answer. This is a deliberate no, not an omission: if a
confidence class is ever wanted it must be derived *from* the cited rules and
stored beside them, never instead of them.

### Defeaters act earlier, and on a different object

| signal | defeated by | why |
|---|---|---|
| `structural_context` | `renamed_symbol_record` | a symbol that was renamed matches by name only by accident |
| `anchored_content` | `reformatted_paths` | equality across a formatter is a property of the formatter |

A defeated signal is **removed**, not down-weighted — weight is the thing this
contract refuses to have. So defeaters always beat positive signals, not because
they are stronger but because they act *earlier*: they remove an input rather
than argue with a conclusion.

### An input that could not be evaluated is not an input that failed

With no diff, `path_rename` cannot be evaluated. `R-CONT-RENAME` therefore does
not apply — and it did not *fail*. An occurrence that really did move with a
renamed file comes out `unresolved`, naming the missing input, instead of `ended`
plus `new`. Slower, and true. This is the absence-of-record doctrine at a third
layer: the runtime witness refuses to read an unread heap as a clean one, the
occurrence contract refuses an ambiguous anchor rather than guessing, and here a
missing diff must not read as "the file did not move".

## Arbitration

Rules apply as a **set**. When several apply:

- **all agree** — that outcome, and `licensed_by` is every applicable rule.
- **they disagree** — `unresolved` / `conflicting-evidence`, *unless* after
  removing every rule dominated by another applicable rule the survivors are
  non-empty and all name the same outcome. Then that is the outcome and
  `licensed_by` is every survivor.
- **a declared refusal pair is present** — `unresolved`, absorbing.

Dominance is declared **pairwise and explicitly**. There is no global ranking,
no priority number, no tie-break by name — all three would decide conflicts
nobody has looked at. The structural rules dominate the 1:1 readings: a record
read at group cardinality knows why the partners are several, and a 1:1 rule
reached its answer by not looking.

One pair is deliberately **not** resolved. An occurrence that is both a copy
source and a participant in a fold is N:M, and none of the six outcomes is N:M.
Neither rule is more informed — each holds a record the other does not consult,
and both records are true — so the answer is `unresolved` /
`conflicting-evidence`, with both ids visible in `applicable_rules` and
`decision_detail.conflicting_rules` while `licensed_by` is empty. Nothing
licensed the refusal; the refusal is what happens when nothing can.

*That pair was not noticed while the rules were being written.* The pair
completeness check found it on its first run.

### Every refusal this policy can emit

Four, and all four are drawn from step 0's vocabulary. **The decision layer
invents no reason values.** When a situation is genuinely unsayable in the senior
vocabulary the senior contract is amended in the open — which has now happened
twice, both times because this rule fired on review rather than because anyone
remembered it unprompted.

| reason | when |
|---|---|
| `no-mapping-evidence` | nothing was observed that could license a link — including the case where the deciding signal could not be *evaluated*, with `inputs_unavailable` naming which |
| `insufficient-evidence-combination` | evidence was observed, some of it defeated, and no declared combination survives |
| `ambiguous-candidates` | several partners, and nothing prefers one — a choice with no grounds |
| `conflicting-evidence` | one observed structure supporting incompatible conclusions — grounds that argue with each other |

The last two are neighbours and opposites, and the distinction is worth keeping
sharp. A draft of this file reported a rule conflict as `ambiguous-candidates`,
which was closer than inventing a value and still wrong: ambiguous candidates are
several partners you cannot choose between, not two readings that contradict each
other. `conflicting-evidence` was added to the senior contract for that, and
`insufficient-evidence-combination` for the floor case above.

`ambiguous-candidates` is also what makes twins work without any rule mentioning
twins. Two occurrences of one pattern in one file agree on path, pattern and
content; a rule that does not include `structural_context` is satisfied by both,
and uniqueness turns that into a refusal instead of into whichever candidate was
enumerated first. Where a structural record *explains* the multiplicity, it is a
branch or a fold instead — that record is the whole difference between a
multiplicity and an ambiguity.

### Two axioms and a theorem

1. **Pair completeness** — every different-outcome pair of declared ids is
   classified exactly once, as a dominance edge or as a deliberate refusal.
2. **Dominance sanity** — edges name existing ids, never self-edge, always span
   different outcomes, never point both ways, and form no cycle.
3. **Totality** — *follows from* 1 and 2 plus the absorbing refusal. Survivors
   cannot span two outcome classes (any two would form a classified pair, and
   whichever way it points one of them has an incoming edge) and cannot be empty
   (a finite acyclic digraph has a source).

The argument never mentions the number of rules. It used to be re-derived by
enumerating this policy's own classification space, which charged an exponential
in *k* for a *k*-independent proof: one extra rule took it from 3^7 x 31 = 67 797
to 3^9 x 63 = 1 240 029 arbitrations, and adding an ordinary rule became a CI
compute decision. So the theorem is now falsified against a **fixed** four-rule
model, outcomes partitioned A, A, B, C — chosen because it contains the shape
the survivor reading turns on, two rules of one outcome surviving together — and
called what it is: bounded falsification, not proof.

The real policy is still verified directly and completely — every subset of its
own rule ids. That sweep is **exponential in the rule count**, `2^n - 1`: six
rules sweep 63 subsets, twelve sweep 4095, twenty sweep over a million. An
earlier revision of this document called it linear, which was wrong — dropping
the `3^k` factor bought a far smaller exponent, not the absence of one. So it
carries a reviewed ceiling of its own and fails CI when exceeded, rather than
growing quietly until someone notices the bill.

## The preregistered matrix

Seven cases in `identity/fixtures/lineage-decision/`, fixed before any mapper,
gated on **exact** equality with `preregistered_cases`. Each is a shape where two
answers are available and the policy has to say which, or say neither.

| # | case | expected |
|---|---|---|
| 1 | `copy-record-dominates-the-single-match` | `branched` — over a real, applicable 1:1 match |
| 2 | `merge-record-dominates-the-single-match` | `merged` — over a real, applicable 1:1 match |
| 3 | `copy-at-one-to-one-is-not-a-branch` | `continued` — cardinality guards the branch out; the deletion is defeated |
| 4 | `defeated-signal-drops-below-the-floor` | `unresolved` / `insufficient-evidence-combination` |
| 5 | `renamed-symbol-defeats-structural-context` | `unresolved` — the name matched by accident |
| 6 | `unavailable-diff-is-not-a-deletion` | `unresolved` — **not** `ended` plus `new` |
| 7 | `blunt-rule-loses-to-uniqueness` | `continued` — and the blunt rule recorded as unable to choose |

Cases 1 and 2 carry an extra burden, because a fixture can be right for the
wrong reason: move the losing rule out of `applicable_rules` and the answer is
still `branched`, with dominance doing no work whatever. The suite cannot notice
on its own — that is applicability again — so `case_obligations` preregisters
what each case must *mechanically* exhibit, and both cases fail if their loser is
quietly reclassified.

**The matrix has already paid for itself.** Trying to write cases 1 and 2 is what
proved the structural rules could not license the outcomes step 0 had already
frozen: their per-partner condition read "a rule of outcome `continued`", every
continued rule requires `structural_context`, and both structural cases change
the enclosing symbol. Three frozen edges had no applicable rule, and a fourth had
one naming the *wrong* outcome — which is worse than a gap. That is also how
`R-CONT-COPY` was found missing.

A half-matrix of the cases that happened to pass would have hidden all of it,
which is why partial credit is not on offer.

## What is deliberately not decided here

- **The mapper.** Still none. This is the decision policy, not the code.
- **Whether a rule set this small is enough.** It is explicitly not exhaustive.
  Adding a rule is a contract edit: declare it, declare its cardinality and
  partner profile, and classify its conflicts. The completeness law covers
  unreachable pairs too, which costs a line and buys the absence of a conflict
  nobody looked at.
- **Whether the fixtures resemble real history.** They do not claim to. Every
  case here is constructed, and the suite verifies structure rather than
  reality — which is exactly the gap the next gate exists to close. Before any
  of this becomes production code it has to be run against a real repository's
  history and then judged on whether the mappings are *useful* downstream, not
  merely well-formed. Architecture that survives only its own fixtures has
  classified its author's imagination.
