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
       + decision_detail.rules_excluded_by_cardinality
       + any further explicitly recorded rejected stage
```

A rule dropped for matching two candidates is *exactly* a mapping that would
change if that rule were made more discriminating; a rule dropped for being the
wrong shape is exactly one that would change if its cardinality were relaxed.
Neither is in
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

#### And every off-path successor needs a record of its own

Cardinality says how many successors there may be. `record_binding` says which
of them the record has to name, and it took two goes to say it correctly.

The copy rule excludes partners at the predecessor's own path — those are where
the occurrence already was, and a continued rule reaches them. Over what is
left, the quantifier was `at_least_one`, which was right when every fixture had
exactly one off-path successor and wrong the moment
`a-copy-into-two-new-files-is-a-branch` arrived with two. Deleting one of that
fixture's two copy records left the branch licensed over both successors: the
unexplained one was absorbed on the strength of its partner profile alone —
`same_rule_message` and `anchored_content`, which any unrelated occurrence of
that defect anywhere in the tree also shows. The rule's own note says the copy
record is what separates a branch from an ambiguity, and a successor with no
record was separated from an ambiguity by nothing.

So it is `every`, over the pool the exclusion leaves. That is not the reading
the old justification rejected — what it rejected was demanding *every*
successor including the one at the predecessor's own path, which the exclusion
had already removed by the time the sentence was written. The exclusion arrived
and the quantifier was never asked again.

The exclusion carries a promise, and the promise is now a condition. Dropping
the same-path partners is justified by the claim that *a continued rule reaches
them* — and nothing asked whether one did. A successor at the predecessor's own
path whose **enclosing symbol changed** satisfies `same_path`, so the exclusion
lifts the record requirement off it, and fails `structural_context`, so no
continued rule reaches it either. It was then absorbed into the branch by
`same_rule_message` and `anchored_content` alone. Three successors, two explained
by copy records and one explained by nothing, and the suite reported OK.

So `excluding.partners_where_same_path_holds` now declares
`requires_applicable_outcome: continued`, and the expectation names, **per
dropped partner**, the rule that reaches it — `excluded_partners_reached_by`,
the same shape as `signals_defeated` and `boundary_defeated`: the thing, and what
explains it. The named rule must be in `applicable_rules` and must conclude that
outcome. It need *not* be in `licensed_by`: a rule that reached a partner and was
then dominated still reached it, which is exactly what
`copy-record-dominates-the-single-match` records.

The per-partner half was the second attempt. The first asked only whether *some*
applicable rule concluded `continued` — and one such rule then discharged the
promise for every dropped partner at once, so a second same-path successor with a
different enclosing symbol rode in on the first one's rescuer while being reached
by nothing itself. Membership standing in for the correct member, written into
the fix for the previous instance of it.

It binds only when something was removed — where no partner sits at the
predecessor's path the exclusion lifts nothing and assumes nothing, which is why
`a-copy-into-two-new-files-is-a-branch` is untouched by it. The outcome is named
in the contract rather than spelled in the checker, for the same reason the
quantifiers are.

And **one rescuer cannot catch two partners**. Naming a rule per partner was not
enough on its own: the same rescuer answered for every dropped partner, so a
second same-path successor with a changed enclosing symbol rode in on the first
one's. What is checkable without the suite becoming a second mapper is the
*shape* — a rule whose cardinality relates one occurrence in a role cannot relate
two of them in one mapping, because two candidates satisfying a 1:1 rule is an
ambiguity, not two rescues.

#### What the rescue map does not establish

That a named rescuer's application actually *includes* the partner it is named
for. With one dropped partner and one named 1:1 rescuer, nothing shows that rule
reaches *that* occurrence rather than some other. Showing it would mean
evaluating the rescuer's `requires_all` against the pair — deciding which rules a
record produces, which is applicability, and which this suite refuses to compute
on purpose.

The residue is a deliberate boundary, not an oversight, and it is written down in
`excluded_partners_rescuer_rule` with the three ways out and what each costs:
let the suite compute applicability for this one purpose and accept a second
implementation of the evidence predicates; have the fixture declare the rescuing
relation as its own expectation, which the corpus cannot currently express
because in `copy-record-dominates-the-single-match` the rescuer reached its
partner and was then *dominated*; or remove the exclusion entirely, which rejects
the very case it exists for. Closing it is a decision about what the integrity
suite is allowed to be, and it belongs to the repository owner.

Making it satisfiable needed a second axis. Git writes **one copy record per
destination**, so no single entry can name both successors; a fold is the
opposite, one record naming all of its sources, and two records naming one each
describe two folds. That difference used to be a property of whichever rule the
checker was written for. It is now declared: `coverage: union_of_entries` on the
copy, `coverage: single_entry` on the fold, required of every rule that binds a
record and rejected if it is a word the vocabulary does not carry.

Both values are pinned, and by the same law. A declared `coverage` that no
input can distinguish from its alternatives is a policy nobody chose — which is
precisely how the copy rule sat at `at_least_one` for twelve fixtures. So each
rule names a **coverage witness**: a committed case, a transform of it the suite
can apply, and the verdict the declared reading must reach on the result. The
sweep applies the transform, evaluates every value in the vocabulary, and
requires two things — that the declared value *disagrees* with each of the
others there, and that it reaches the *declared verdict*.

The copy's witness is `a-copy-into-two-new-files-is-a-branch` untransformed
(`accepts`): two off-path successors with one record each, which
`union_of_entries` admits and `single_entry` cannot. The fold's is
`a-fold-across-files-is-still-a-merge` with its record spread over one source
each (`rejects`): two folds into one successor, not the one transformation the
mapping claims.

An earlier version of this section reported the fold's value as pinned only by
being the *stronger* reading, on the grounds that the separating input was an
invalid mapping no valid case could express. That confused the *record* being
partial with the *input* being unpreregisterable, and it was a disclosed gap
standing in for a closed one. The first draft of the law that replaced it was
also wrong, and in an instructive way: it required only that the readings be
*distinguishable* on the witness, which stayed green when the fold's value was
flipped — a law proving two options differ says nothing about which was taken.
The verdict is the half that makes it bite.

### And a smaller law: no cross-reference to nothing

The contract's prose is full of backticked names — sections, rules, record
fields, obligations, signals, evidence kinds, binding tokens. Every one of them
must now be a name one of the two contracts actually defines, at any depth, or a
fixture field, or a name declared in `retired_names`.

The gate exists because I wrote `what_the_suite_refuses_to_compute` into a
section whose entire subject is claims nothing checks. The key has never existed.

Its own first two drafts are the more useful lesson. The first read only
top-level list-valued sections and demanded two underscores, so `rules.*.why`,
every object-valued section and any name like `missing_reference` went unread —
a gate covering part of what its declaration claimed, written into the gate
about claims nothing checks. The second matched the identifier pattern anywhere
in a line and so found `excluded_by_cardinality` *inside* the correct reference
`decision_detail.rules_excluded_by_cardinality`, inventing a dangling reference
out of a sound one; whole backticked spans are now parsed segment by segment.

`retired_names` carries the names the contract mentions *because they are gone* —
`requires_all_scope`, replaced by `record_binding`; `defeated_signals`, a second
spelling of `signals_defeated`; `excluded_by_cardinality`, a top-level twin of
`decision_detail.rules_excluded_by_cardinality`. Listing a name there is a claim
that the prose citing it is history, and a reader can check that claim against
the sentence. It is not a way to silence the gate.

Run against the corpus for the first time, it found exactly one real defect: a
`why` contrasting two classifications named `at_or_above_the_floor` by a
truncation of it, so the sentence pointed at no branch of the mapping it was
describing.

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
| `R-CONT-SAME-SITE` | `continued` | 1:1 | `same_path`, `structural_context`, `anchored_content`, `same_pattern_id` |
| `R-CONT-DRIFT` | `continued` | 1:1 | `same_path`, `structural_context`, `line_drift`, `same_pattern_id` |
| `R-CONT-RENAME` | `continued` | 1:1 | `path_rename`, `structural_context`, `anchored_content`, `same_rule_message` |
| `R-CONT-COPY` | `continued` | 1:1 | `copy_record`, `structural_context`, `anchored_content`, `same_rule_message` |
| `R-BRANCH-COPY` | `branched` | 1:N, N>=2 | `copy_record` (group) + per successor: `same_rule_message`, `anchored_content` |
| `R-MERGE-FOLD` | `merged` | N:1, N>=2 | `merge_record` (group) + per predecessor: `same_rule_message`, `anchored_content` |

**Every continuation rule asks what the analyser SAID, not only where it was.**
`same_path`, `structural_context`, `anchored_content`, `path_rename` and
`copy_record` all describe a *place* and a *text*. None of them says the finding
is the same finding, so a diagnostic reclassified or reworded at a site that did
not otherwise change satisfied every one of them and inherited a lineage it had
not earned. R-CONT-DRIFT was given `same_pattern_id` for exactly this reason and
the three rules beside it were never asked — a claim applied where it was named
and not at the adjacent site, which is this branch's signature defect.

Which kind depends on whether the path moved, and the choice is forced rather
than stylistic. The same-path rules take `same_pattern_id`: `finding-pattern/v1`
hashes path, rule and message together, so with the path held equal the id
differs exactly when the rule or the message differs. The rules that survive a
move cannot: the path is *in* the hash, so a renamed or copied occurrence can
never share a pattern id with its predecessor, and requiring one would make both
rules unsatisfiable on real data. They take `same_rule_message`, the
path-independent kind the sixth senior amendment added for the group profiles —
one comparison over the rule and the message together, never two halves that
would reach the evidence floor between them.

Cases 17, 18 and 19 are where those requirements are either doing work or are
decoration, and they are three cases rather than one on purpose: 18 holds the
rule id fixed and moves the message, 19 does the opposite, and the copy does not
get the rename's result by symmetry.

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

Six, and all six are drawn from step 0's vocabulary. **The decision layer
invents no reason values.** When a situation is genuinely unsayable in the senior
vocabulary the senior contract is amended in the open — which has now happened
twice, both times because this rule fired on review rather than because anyone
remembered it unprompted.

| reason | when |
|---|---|
| `no-mapping-evidence` | nothing was observed that could license a link — including the case where the deciding signal could not be *evaluated*, with `inputs_unavailable` naming which |
| `insufficient-evidence-kind` | a defeat left **fewer** kinds standing than the senior floor — there the shortage really is of kinds |
| `insufficient-evidence-combination` | a defeat left the floor cleared, and no declared combination survives |
| `ambiguous-candidates` | several partners, and nothing prefers one — a choice with no grounds |
| `conflicting-evidence` | one observed structure supporting incompatible conclusions — grounds that argue with each other |
| `missing-occurrence-id` | the finding has no occurrence identity, so there is no subject to relate — settled at stage 0, before any evidence is read |

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

The cases below live in `identity/fixtures/lineage-decision/`, fixed before any
mapper, and are gated on **exact** equality with `preregistered_cases`. The table
is the count; this sentence deliberately does not repeat it, because the number
was written here as `Ten` and went stale the moment cases 11 and 12 landed — the
third time on this branch that a count restated in prose has drifted from the
list beside it. Each is a shape where two
answers are available and the policy has to say which, or say neither.

### Stage 0: eligibility, and why it is not a rule

`identity/occurrence.py` returns `None` for an occurrence id when the producer
run id is missing or the physical anchor is ambiguous, and `aggregate/normalize.py`
writes that `None` into the `normalized-findings/v2` record. It is ordinary
output of a run without producer provenance — not malformed input — and
`finding-lineage/v1` has frozen `missing-occurrence-id` for it since step 0.

The decision policy had no path to it. The procedure began at COLLECT, no
`reason_mapping` branch emitted it, and the relation matrix could not express it
at all, because a relation record has to name its subject and the name is
exactly what is absent. So the procedure now opens at stage 0:

> **0. ELIGIBILITY.** A finding whose `occurrence_id` is null is `unresolved` /
> `missing-occurrence-id`. No signals are collected, no candidates are
> constructed, no rule is matched, and nothing is arbitrated.

Two things are deliberate. It **absorbs**: no later combination of `same_path`,
`anchored_content`, a rename record or boundary evidence rescues the decision,
which keeps an identity limitation on `unresolved` rather than letting it drift
to `ended` or `new`. And the refusal is **input-local** — it annotates the
normalized finding, which is already the subject, instead of emitting an edge.
No synthetic id, no ordinal, no hash of the physical anchor, and no `frm: null`
standing in for a reference. Upstream refused to invent an identity; this layer
does not restore one.

Those four are `eligibility.forbids`, and they are **tokens, not sentences**.
Each names a set of output fields — `occurrence_id`; `ordinal` / `index` /
`position`; `anchor_hash` / `physical_anchor` / `anchor_id`; `frm` / `to` — that
the integrity suite holds out of the eligibility expectation schema and out of
every fixture's `expect`, and the declared set and the enforceable set must be
equal in both directions. They were four sentences first, and nothing read them:
replacing all four with `["anything", "else"]` left the corpus and the suite
green. That is the defect this whole document keeps describing — a claim applied
where it was named and never asked of the adjacent site — appearing inside the
section written to close another instance of it.

Its cases live in `identity/fixtures/lineage-eligibility/`, apart from the
relation matrix, and cover both sides:
`an-unidentified-finding-in-revision-a-is-unresolved` (a predecessor that cannot
be named) and `an-unidentified-finding-in-revision-b-is-unresolved` (a
successor). The relation schema still requires a string occurrence id, and is
not relaxed — that requirement is what stops an unanswerable edge being
preregistered.

Each case's limitations are checked by **running the producer**, not by
restating its rules. The suite calls `identity/occurrence.py`'s `resolve()` on
the finding as written — reading the two inputs a normalized record does not
carry, producer provenance and anchor ambiguity, off the declared limitations so
the fixture still picks its own scenario — and requires that the returned id is
`None` and the returned limitation list matches the declared one exactly.

That replaced a weaker check which asked only that some declared token carried
the `occurrence-id-unavailable:` prefix. It passed limitation sets `resolve()`
could not have produced: both cases set `start_column: null` and neither declared
`physical-anchor-missing:start-column`, which `resolve()` appends unconditionally
in that case, so both fixtures froze a record the producer cannot emit. It would
also have accepted `occurrence-id-unavailable:path` on a finding that has a path.
Reimplementing the predicates in the checker would only have frozen a second
opinion about them; calling the producer freezes the producer.

The two cases now differ in anchor quality on purpose. The revision-A finding has
a complete anchor and exactly one limitation — the missing provenance — because a
finding can lose its identity without its anchor being degraded too. The
revision-B finding has no start column and carries both tokens, one blocking and
one not.

| # | case | expected |
|---|---|---|
| 1 | `copy-record-dominates-the-single-match` | `branched` — over a real, applicable 1:1 match |
| 2 | `merge-record-dominates-the-single-match` | `merged` — over a real, applicable 1:1 match |
| 3 | `copy-at-one-to-one-is-not-a-branch` | `continued` — cardinality guards the branch out; the deletion is defeated |
| 4 | `defeated-signal-drops-below-the-floor` | `unresolved` / `insufficient-evidence-combination` |
| 5 | `renamed-symbol-defeats-structural-context` | `unresolved` — the name matched by accident |
| 6 | `unavailable-diff-is-not-a-deletion` | `unresolved` — **not** `ended` plus `new` |
| 7 | `blunt-rule-loses-to-uniqueness` | `continued` — and the blunt rule recorded as unable to choose |
| 8 | `copy-source-that-is-also-a-fold-refuses` | `unresolved` / `conflicting-evidence` — N:M, and none of the six outcomes is N:M |
| 9 | `every-candidate-blunted-is-an-ambiguity` | `unresolved` / `ambiguous-candidates` — every rule matched both, and none preferred one |
| 10 | `a-defeat-can-leave-too-few-kinds` | `unresolved` / `insufficient-evidence-kind` — one kind survives against a floor of two |
| 11 | `a-recorded-rename-is-not-an-unresolved` | `continued` — the twin of case 6, with the record readable |
| 12 | `an-edit-elsewhere-is-still-the-same-defect` | `continued` — the line moved and the text changed |
| 13 | `a-copy-into-two-new-files-is-a-branch` | `branched` — and no successor shares the predecessor's `pattern_id` |
| 14 | `a-fold-across-files-is-still-a-merge` | `merged` — the folded predecessor lives in another file |
| 15 | `an-ambiguity-outranks-a-cardinality-rejection` | `unresolved` / `ambiguous-candidates` — both rejecting stages fire, and only one of them is an answer |
| 16 | `a-different-defect-at-the-same-site-is-not-a-drift` | `unresolved` / `no-mapping-evidence` — the site is shared and the diagnostic is not |
| 17 | `a-reclassified-defect-at-an-unchanged-site-is-not-a-continuation` | `unresolved` / `no-mapping-evidence` — nothing about the site changed, and the analyser changed its mind |
| 18 | `a-reclassified-defect-across-a-rename-is-not-a-continuation` | `unresolved` / `no-mapping-evidence` — the file moved, the text came with it, and the message was reworded |
| 19 | `a-reclassified-defect-across-a-copy-is-not-a-continuation` | `unresolved` / `no-mapping-evidence` — the copy's mirror, and the half where the rule id moves instead |

Cases 1 and 2 carry an extra burden, because a fixture can be right for the
wrong reason: move the losing rule out of `applicable_rules` and the answer is
still `branched`, with dominance doing no work whatever. The suite cannot notice
on its own — that is applicability again — so `case_obligations` preregisters
what each case must *mechanically* exhibit, and both cases fail if their loser is
quietly reclassified.

Cases 11 and 12 close a coarser one. Four rules license `continued`, so
exercising any of them ticked that outcome off — and `R-CONT-RENAME` and
`R-CONT-DRIFT` were reached by no case at all. Either could be rewritten into a
different policy with the whole suite green: swap the rename rule's `path_rename`
for `same_path`, or the drift rule's `line_drift` for `path_rename`, and nothing
went red. Worse, the suite carried an argued-for exemption saying this was fine —
that the rename rule was constrained by the senior corpus instead. It is not:
`finding-lineage/v1` fixtures name no decision rule ids, and this suite never
arbitrates them. The gate is now **per rule**, and each of the two new cases
carries `rule_licensed_alone`, so the rule it reaches is the only rule applicable
and the conclusion rests on that rule's requirements alone.

Case 11 is deliberately the same physical move as case 6 — same paths, same
symbol, same content — differing in one respect only: whether `path_rename` could
be evaluated. Case 6 cannot see the rename and answers `unresolved`; case 11 can
and answers `continued`. Holding the movement fixed and varying only the
readability of the record is what makes the absence-of-record doctrine visible as
a decision rather than a paragraph. Case 12 rests on the one rule that does *not*
require `anchored_content`: the text really did change, and a defect may be
edited without ceasing to be the same defect.

What the per-rule gate does **not** do is bind a rule's `requires_all` to the
evidence a fixture carries. Reaching a rule proves the rule is reachable, not
that its stated requirements are why it applied — that is applicability, which
fixtures declare and this suite refuses to compute.

Cases 9 and 10 close a coverage gap an outcome-shaped gate could not see. The
policy emits five refusal reasons; `unresolved` read as covered while two of
them — `ambiguous-candidates`, which `arbitration.multiplicity` selects, and the
below-floor half of the defeat mapping — were pinned by no case at all, so
either branch could be repointed with the suite still green. The gate now
requires every emitted reason to be exercised, because several reasons share one
outcome and an outcome cannot stand in for them.

Case 8 is the one the contract had already decided and nothing pinned. The N:M
refusal was frozen in `deliberately_unresolved_conflicts` — found, as that section
says, by the pair-completeness check rather than by anyone noticing it — and no
fixture exercised it until a suite check demanded a witness. A declared refusal
with no case is a decision frozen in name only.

**The matrix has already paid for itself.** Trying to write cases 1 and 2 is what
proved the structural rules could not license the outcomes step 0 had already
frozen: their per-partner condition read "a rule of outcome `continued`", every
continued rule requires `structural_context`, and both structural cases change
the enclosing symbol. Three frozen edges had no applicable rule, and a fourth had
one naming the *wrong* outcome — which is worse than a gap. That is also how
`R-CONT-COPY` was found missing.

A half-matrix of the cases that happened to pass would have hidden all of it,
which is why partial credit is not on offer.

## Two rejecting stages, one answer

Step 4 records a uniqueness rejection and a cardinality rejection separately, and
always has. What it never said is which of them the record's `reason` comes from
when both fire in one mapping — so a mapper could have reported either and been
reading the contract correctly. No case exercised the coincidence: fourteen
fixtures had one rejection or the other and never both.

`reason_selector` ranks them, and the order is total and readable from the
record's own fields, which is the point — no step of it needs applicability:

1. eligibility refused → `missing-occurrence-id` (absorbs before evidence is read)
2. conflicting rules → `conflicting-evidence`
3. ambiguous candidates → `ambiguous-candidates`
4. a defeat left no surviving rule → `insufficient-evidence-{kind,combination}`
5. otherwise → `no-mapping-evidence`

**Cardinality is deliberately nowhere in that order.** It is the one rejection
that is not about the evidence at all: it says a rule does not govern this shape,
which is not a reason a relation failed. `rules_excluded_by_cardinality` stays in
the record as provenance for the recall set and selects nothing.
`an-ambiguity-outranks-a-cardinality-rejection` is where both stages fire at once
and the ambiguity answers.

## A refusal that names no predecessor carries no pair evidence

A b-side `unresolved` has `frm: null`. `signals_defeated` says why a **relation**
signal was removed and `evidence_surviving` says which kinds survived **in a
pair** — and there is no pair here for either to be about.

Three fixtures used to carry the a-side's defeat across to the b-side by
symmetry. That recorded evidence about a relation the record itself does not
state, and it also made the b-side reason follow from the a-side's floor
arithmetic rather than from anything observable on the b-side. They now say what
is true there: nothing links this occurrence back, and nothing says it is new —
`no-mapping-evidence`. If the reason ever needs to explain *which* candidate
predecessors were tried and rejected, that is a candidate-attempt trace and a
different record shape, not this one.

## What is deliberately not decided here

- **The mapper.** Still none. This is the decision policy, not the code.
- **Whether the integrity suite may compute applicability. It may not, and that
  is settled.** Fixtures preregister `applicable_rules`; this suite checks shape,
  carried records and arbitration, and never re-evaluates a rule's predicates. A
  checker that did would be a second mapper — hidden, unversioned, and certain to
  disagree with the first one the day either changed, with both equally
  confident. Applicability is first computed by the reference evaluator at the
  real-history gate, once, in one place. This is an architectural boundary of
  step 1, not an open question.
- **Whether a named rescuer actually reaches its excluded partner.** It follows
  from the line above that this cannot be shown here:
  `excluded_partners_reached_by` pins that every dropped partner is named, that
  the named rescuer is applicable and concludes the required outcome, and that no
  rescuer catches more partners than its cardinality relates — but proving the
  rule's application *includes* that occurrence means evaluating its
  `requires_all`, which is applicability. `excluded_partners_rescuer_rule`
  records the boundary. In the reference evaluator the link becomes computable
  naturally, by the one evaluator rather than by a second hidden inside a test.
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
