# Finding lineage — following one finding across revisions

**Status: contract frozen, implementation not started.** This is Own.NET#266
slice 2, step 0. Nothing in `aggregate/`, `identity/pattern.py`,
`identity/occurrence.py` or `runtime/` changes here, and no mapping code exists
yet. What is fixed is *what a mapping may claim*, *what it must show for the
claim*, and *the cases it will be judged on* — written down before an algorithm
exists, so the algorithm cannot quietly select the cases that flatter it.

| | question | contract | status |
|---|---|---|---|
| `pattern_id` | *which finding is this, as a pattern?* | `finding-pattern/v1` | frozen, implemented |
| `occurrence_id` | *which physical occurrence, in which run?* | `finding-occurrence/v1` | frozen, implemented |
| `lineage_id` | *is this the same finding I saw in the previous revision?* | [`finding-lineage/v1`](../contracts/finding-lineage-v1.json) | **frozen, not implemented** |

## The unit of analysis

A lineage mapping takes **one occurrence in revision A** and asks what it
corresponds to **in revision B**. Not a pattern, not a file, not a report: one
physical occurrence, from one producer run, against another.

That choice is forced by what already exists. `pattern_id` deliberately collides
— two findings with the same `(path, rule, message)` are one repeated pattern —
so a mapping keyed on it could not tell two occurrences in one file apart, and
could not say that one of them was fixed while the other was not. `occurrence_id`
is what tells them apart, and it exists only within a single producer run: it is
built from `producer_run_id`, so the same physical defect in two runs has two
different occurrence ids **by construction**. Lineage is precisely the relation
those two ids do not carry.

Hence the three-way split, which this contract freezes:

- **`pattern_id`** — the logical pattern. Stable across runs by construction,
  and therefore *not* evidence of continuity: two unrelated occurrences of one
  pattern share it.
- **`occurrence_id`** — one physical instance within one producer run. Cannot
  span revisions, and must not be made to.
- **`lineage_id`** — cross-revision identity, and **only** that. It is not
  derived from the other two; it is *earned* by mapping evidence, and refused
  when the evidence is not there.

## What a mapping may conclude

Six outcomes, and no others. The vocabulary is in
[`contracts/finding-lineage-v1.json`](../contracts/finding-lineage-v1.json).

| outcome | means | `lineage_id` |
|---|---|---|
| `continued` | exactly one successor, and the evidence establishes it | inherited if the predecessor has one, else minted once for both |
| `branched` | one predecessor, several equally-supported successors | a fresh child id per successor, each recording the parent |
| `merged` | several predecessors, one successor | a fresh id for the successor, recording *every* parent |
| `unresolved` | **the evidence does not decide**, on either side | `null` + side + reason |
| `ended` | no successor, and *that* is positively evidenced | nothing minted + boundary evidence |
| `new` | no predecessor, and *that* is positively evidenced | a fresh **root** id + boundary evidence |

**The load-bearing rule.** Absence of mapping evidence is `unresolved`. It is
not a new lineage, and it is not the same lineage. This is the same invariant the
occurrence contract already enforces one level down — *identity is refused, not
approximated* — and the same one the runtime witness enforces about a heap it did
not read: **absence of a record is not a semantic outcome.** A mapper that
answers "new" whenever it fails to find a predecessor manufactures a birth event
out of its own ignorance, and every metric built on "findings introduced this
revision" then measures the mapper.

**`unresolved` is symmetric, and that is structural.** It anchors on the A side
(*a predecessor whose successor was not established*) or on the B side (*an
occurrence in B whose predecessor was not established*). The first draft of this
contract had only the A side, and the consequence was not a gap in the prose: an
unmatched occurrence in revision B had **nowhere to go but `new`**, so the
schema itself manufactured the birth event the doctrine forbids. A defect in the
vocabulary is one no implementation can avoid, which is exactly why the
vocabulary is frozen before the mapper.

**Ambiguity is expressed, not resolved.** A copy of one occurrence into two
places is `branched`, not a coin-flip between two successors with the loser
discarded. Two equally plausible move candidates are `unresolved` — and so is
each of the two candidates, seen from B. The occurrence contract already refuses
an ordinal tiebreaker for exactly this reason — an ordinal makes identity depend
on emission order — and a lineage tiebreaker would be the same defect across
time.

**Nothing is dropped in silence.** Every occurrence on both sides appears in the
mapping record under some outcome. An occurrence the record does not mention is
indistinguishable from one the mapper forgot, so "unexplained" is a thing that
gets *said*, not a thing that gets omitted.

## Ends and births are earned, exactly like continuations

`ended` and `new` are the two outcomes that assert something about the *world*:
that a lineage stopped, or that one began. They are therefore **not** reachable
by failing to find a match — that is `unresolved` — and the contract keeps two
separate vocabularies so the two can never be confused in a stored record:

| vocabulary | prefix | says | belongs to |
|---|---|---|---|
| identity limitation | `lineage-id-unavailable:` | why the *mapper* could not decide | `unresolved` only |
| boundary evidence | `boundary:` | what the *tree* shows about an edge | `ended` and `new` only |

Each boundary kind names the machine-readable field it is read from —
`containing-file-deleted` from `deleted_paths`, `enclosing-site-removed` from
`removed_symbols`, and so on — because a boundary asserted only in prose is the
absence of a match wearing a better word. The integrity suite reads that field
and checks the fact is really there, and really about *this* occurrence.

Each kind also names what **defeats** it. Positive evidence that another record
explains away is not evidence: a deleted path that appears as a rename source
did not die, and an added path that appears as a copy target was not born. That
defeater is what separates
[`copy-branches-without-a-winner`](../identity/fixtures/lineage/copy-branches-without-a-winner.json)
from
[`added-file-is-an-evidenced-birth`](../identity/fixtures/lineage/added-file-is-an-evidenced-birth.json):
both put an occurrence in a file that did not exist in revision A, and the only
thing that tells a copy from a birth is whether the arrival has a recorded
source.

The same applies at the other edge, and it is easy to miss: a path in
`deleted_paths` that *also* appears as `copies[].from` was not a death. The
deletion is a fact about the path; the copy record says the contents — and any
occurrence in them — went somewhere.
[`deleted-source-survives-in-its-copy`](../identity/fixtures/lineage/deleted-source-survives-in-its-copy.json)
is that case, and it is adversarial precisely because the boundary evidence
genuinely fires.

## What the lineage ids do

The graph semantics are fixed here rather than left to the mapper, because a
mapper free to choose between inheriting and minting decides by itself whether a
lineage survives reformatting, and a mapper free to choose a merge id decides by
itself which of several defects "the" surviving one is. Those are answers to the
questions this contract exists to ask.

- **inherit** — the predecessor already carries a lineage: the successor takes
  *that* id. A re-mint would read as a new defect appearing exactly where an old
  one was proven to persist.
- **mint** — first proven 1:1 edge between two unlinked occurrences: mint once,
  and bind both ends to it.
- **branch** — every successor gets its own fresh child id recording
  `parent_lineage_ids`. No successor inherits the predecessor's id, because
  inheriting *is* choosing, and `branched` exists precisely to refuse a choice.
- **merge** — the successor gets a freshly minted id recording
  `parent_lineage_ids` for **every** predecessor. Inheriting one parent's id
  would elect it silently and orphan the rest.

### When a lineage id exists at all

> A `lineage_id` exists when **membership in an established lineage graph is
> known**. `unresolved` establishes no membership, and so seeds nothing.

An earlier draft said instead that an id exists exactly when an edge was proven.
Tidier, and wrong: it makes a **root node unrepresentable**. Take a legal
sequence — `occ-b2` is an evidenced birth in r1→r2, then branches into `c1` and
`c2` in r2→r3. The branch owes its children a parent *lineage*, and under the
edge-only rule the parent has none. What is left is an empty parent, an
occurrence id smuggled into a lineage field, or a retroactive mint no rule
describes.

So the outcomes that build graph structure seed their own roots:

| outcome | seeds |
|---|---|
| `unresolved` | nothing, on either side — a refusal that minted an id would *be* membership |
| `new` | a fresh **root** id for its B occurrence: a node with no incoming edge |
| `continued` | mint-once-and-bind-both if neither end is linked; inherit if the predecessor is |
| `branched` | an unlinked predecessor is seeded with a root **first**; children then record *that* id |
| `merged` | every still-unlinked predecessor is seeded with its own root **first** |
| `ended` | nothing — a linked predecessor has its lineage terminated, an unlinked one stays a terminal occurrence with no pretended past |

`ended` is deliberately outside the seeding rule. It creates no structure, so
requiring an id there would inflate "lineage" into "every singleton has one".

### Parents are lineages, not occurrences

`parent_lineage_ids` holds **lineage** ids. Never occurrence ids — and this is
not pedantry about naming. `occurrence_id` is built from `producer_run_id` and
therefore cannot span runs *by construction*; one stored in a cross-revision
field is a claim made out of the one identifier that provably cannot carry it.
It is the same type confusion the three-way split at the top of this document
exists to prevent, one level up.

Fixtures cannot know a value the mapper has not minted yet, so they write
`lin-of:<occurrence_id>` — *the lineage of* that occurrence, seeded as a root if
it has none — or a literal id the case already declared in
`established_lineage`. The integrity suite resolves those references and checks
every predecessor contributes exactly one parent lineage, and that no bare
occurrence id appears in the field.

What remains open is which evidence licenses each outcome — not what the ids then
do.

## Evidence is stored, and stored separately from the id

A mapping record carries the evidence that produced it, in a field of its own.
Not merged into the id, not summarised into a score that discards which signals
fired.

```jsonc
{
  "outcome": "continued",
  "lineage_id": "…",
  "from": { "occurrence_id": "…", "revision": "…" },
  "to":   { "occurrence_id": "…", "revision": "…" },
  "evidence": [
    { "kind": "same_pattern_id",     "detail": "…" },
    { "kind": "path_rename",         "detail": "similarity 96%" },
    { "kind": "structural_context",  "detail": "enclosing symbol unchanged" },
    { "kind": "anchored_content",    "detail": "line content identical" },
    { "kind": "line_drift",          "detail": "+12 lines" }
  ],
  "mapping_provenance": {
    "from_run": "…", "to_run": "…",
    "from_revision": "…", "to_revision": "…",
    "mapper": "…", "mapper_version": "…",
    "mapper_config_digest": "…", "contract_version": "finding-lineage/v1"
  }
}
```

A refusal is the same record with the conclusion refused rather than drawn — the
outcome, the side or the boundary evidence, and the same provenance:

```jsonc
{ "outcome": "unresolved", "side": "b", "lineage_id": null,
  "from": null, "to": { "occurrence_id": "…", "revision": "…" },
  "reason": "lineage-id-unavailable:ambiguous-candidates",
  "mapping_provenance": { "…": "…" } }

{ "outcome": "ended", "lineage_id": null,
  "from": { "occurrence_id": "…", "revision": "…" }, "to": [],
  "boundary_evidence": [ { "kind": "boundary:containing-file-deleted",
                           "detail": "Broker/Gone.cs in deleted_paths" } ],
  "mapping_provenance": { "…": "…" } }
```

Two reasons this is a requirement rather than a nicety. A mapping whose evidence
is not recorded cannot be re-judged when the rule changes — the only way to know
whether an old mapping would still be made is to have kept what made it. And an
id without its evidence invites the reading that the id *is* the fact, when it is
only a conclusion; the same reason the runtime witness prints the field name at
every hop instead of asserting "this object is retained".

`same_pattern_id` is listed as evidence but is **never sufficient alone**: it is
exactly the signal that collides on purpose. The contract records which evidence
kinds may carry a `continued` on their own and which may not.

Today none may, so the floor is a **count**: a `continued` names at least two
kinds, and `minimum_evidence_kinds_for_continued` states that as data rather than
prose. A floor only written in prose is one a preregistered case can quietly sit
under — which three of these cases did, naming only the signal that *told two
occurrences apart* instead of the evidence that carried the mapping.

## Mapping provenance binds both sides

A mapping is a statement about two specific runs over two specific revisions. It
carries `mapping_provenance` naming both, so it cannot later be read outside the
context that computed it.

Without that, a stored mapping is a claim with no subject: "these two findings are
the same" is unfalsifiable unless you can say *which two runs, over which two
revisions, under which mapper*. `producer-provenance/v1` already establishes this
discipline for a single run — a run id that names the analysis rather than the
normalization — and lineage needs the pair.

The mapper's own identity belongs there too. Two mappers disagreeing about one
pair of runs is a fact worth being able to see, and it is invisible if the record
says only that a mapping exists.

A bare name is not that identity, though. The promise "an old mapping can be
re-judged when the rule changes" needs to survive the rule changing *inside* one
mapper: two runs of `own-lineage` with different thresholds are a disagreement
that would read as a contradiction. So the record pins `mapper_version`, a
`mapper_config_digest` of the configuration actually in force, and the
`contract_version` the mapping was made under. Without those three, "would this
mapping still be made today?" has no answer, and the evidence field is kept for
a re-judgement that can never be performed.

## The fixture matrix, preregistered

Thirteen cases, fixed **before** the algorithm, in
[`identity/fixtures/lineage/`](../identity/fixtures/lineage/). Each declares its
inputs and its expected outcome. `identity/tests/test_lineage_contract.py`
checks the matrix is complete and well-formed — it does **not** run a mapper,
because there is none.

| # | case | expected |
|---|---|---|
| 1 | `line-drift-continues` | `continued` |
| 2 | `rename-with-context-continues` | `continued` |
| 3 | `twin-patterns-stay-distinct` | two lineages, **not** collapsed |
| 4 | `one-twin-fixed-other-untouched` | `ended` + `continued`; the survivor does **not** inherit the other's fate |
| 5 | `copy-branches-without-a-winner` | `branched` — no arbitrary winner |
| 6 | `duplicate-sites-merge-into-one` | `merged` — no arbitrary survivor |
| 7 | `two-candidates-unresolved` | `unresolved` on **both** sides |
| 8 | `deleted-file-ends` | `ended`, earned by the deletion record |
| 9 | `deleted-source-survives-in-its-copy` | `continued` — the deletion is **defeated** by the copy record |
| 10 | `added-file-is-an-evidenced-birth` | `new` + a seeded **root** id |
| 11 | `coincidence-is-not-a-mapping` | `unresolved` on both sides — **not** `ended` + `new` |
| 12 | `presentation-move-preserves-proven-lineage` | lineage id unchanged |
| 13 | `rerun-is-byte-stable` | byte-stable mapping artifact |

Cases 3, 4, 6, 7, 9 and 11 are the adversarial core: each is a shape where a
plausible mapper produces a confident wrong answer. 3 and 4 are why the unit is
the occurrence rather than the pattern. 7 and 10 are where "probably the same"
has to become `unresolved` instead of a guess — and 11 is the case that caught
this contract's own first draft, which turned a refused mapping into a death and
a birth. 9 is the adversarial case against the boundary evidence itself: the
deletion really does fire, and is still wrong, because the same revision records
the path as a copy source. 6 is the mirror of 5: an N:1 collapse looks exactly like 1:1 plus a
fix, so a mapper that continues one predecessor and ends the other reports a
repair that never happened. 8 and 10 are the positive controls that make `ended`
and `new` falsifiable at all; without them those words could only ever be reached
by the route the contract forbids. 13 is what makes any of it re-checkable — a
mapping artifact that differs run to run cannot be diffed, and a lineage you
cannot diff is a lineage you cannot audit.

## What is deliberately not decided here

- **The algorithm.** Which signals to combine, in what order, with what
  thresholds. This contract fixes what the answers may be and what must be shown
  for them; it does not pick the mapper.
- **Where mappings are stored**, and whether they ride in `findings.json` or a
  sidecar. That interacts with the payload schema, which slice 1B froze, and it
  is an integration decision rather than a semantic one.
- **Ordering** of the six outcomes, or a confidence score. A score that collapses
  `unresolved` and a weak `continued` into one number would undo the distinction
  this contract exists to protect.
The lineage-id semantics used to sit on this list, in two rounds. First "one per
successor" and "the successor records every predecessor" — a description of a
record that never says what id anything gets, leaving the mapper to settle the
shape of the lineage graph as a side effect. Then whether an evidenced `new`
seeds a root, which looked like a free choice until the r1→r2→r3 branch above
showed it is not one: the alternative is not "no id", it is an occurrence id in
a lineage field. Both came off the list. Neither was safe to leave to the
implementation, and both were cheap to settle while no implementation exists.

## Dependency, stated honestly

This step deliberately writes no production code, because the seam it would sit
on is under review. [#62](https://github.com/PhysShell/OwnAudit/pull/62) touches
`aggregate/normalize.py` and the SARIF reader, but leaves locationless results
*outside* `findings` — so the population that receives `pattern_id` /
`occurrence_id` is unchanged, and this contract should survive it untouched.

If review of #62 instead moves the boundary of what counts as a physical finding,
or changes `physical_anchor` or occurrence semantics, that is a real dependency
event and **this contract is revised first**. Nothing has to be thrown away,
because nothing has been built on it yet.
