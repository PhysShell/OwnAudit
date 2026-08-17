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
| `continued` | exactly one successor, and the evidence establishes it | minted |
| `branched` | one predecessor, several equally-supported successors | one per successor, all recorded as a set |
| `merged` | several predecessors, one successor | the successor records all of them |
| `unresolved` | **the evidence does not decide** | `null` + reason |
| `ended` | no successor, and *that* is evidenced (the file is gone, the site is gone) | `null` + reason |
| `new` | no predecessor, and *that* is evidenced | `null` + reason |

**The load-bearing rule.** Absence of mapping evidence is `unresolved`. It is
not a new lineage, and it is not the same lineage. This is the same invariant the
occurrence contract already enforces one level down — *identity is refused, not
approximated* — and the same one the runtime witness enforces about a heap it did
not read: **absence of a record is not a semantic outcome.** A mapper that
answers "new" whenever it fails to find a predecessor manufactures a birth event
out of its own ignorance, and every metric built on "findings introduced this
revision" then measures the mapper.

**Ambiguity is expressed, not resolved.** A copy of one occurrence into two
places is `branched`, not a coin-flip between two successors with the loser
discarded. Two equally plausible move candidates are `unresolved`, not the one
that sorted first. The occurrence contract already refuses an ordinal tiebreaker
for exactly this reason — an ordinal makes identity depend on emission order —
and a lineage tiebreaker would be the same defect across time.

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
  "mapping_provenance": { "from_run": "…", "to_run": "…", "…": "…" }
}
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

## The fixture matrix, preregistered

Ten cases, fixed **before** the algorithm, in
[`identity/fixtures/lineage/`](../identity/fixtures/lineage/). Each declares its
inputs and its expected outcome. `identity/tests/test_lineage_contract.py`
checks the matrix is complete and well-formed — it does **not** run a mapper,
because there is none.

| # | case | expected |
|---|---|---|
| 1 | clean line drift | `continued` |
| 2 | git rename, same structural/context evidence | `continued` |
| 3 | two identical patterns in one file | two lineages, **not** collapsed |
| 4 | one of the two repeats fixed | the other does **not** inherit its fate |
| 5 | one occurrence copied into two places | `branched` — no arbitrary winner |
| 6 | a move with two equally plausible candidates | `unresolved` |
| 7 | the file is deleted | `ended` — no fabricated successor |
| 8 | same basename, roughly the same line, nothing else | **not** a mapping |
| 9 | presentation-only line movement over an already-proven lineage | lineage unchanged |
| 10 | re-run on identical inputs | byte-stable mapping artifact |

Cases 3, 4, 6 and 8 are the adversarial core: each is a shape where a plausible
mapper produces a confident wrong answer. 3 and 4 are why the unit is the
occurrence rather than the pattern. 6 and 8 are where "probably the same" has to
become `unresolved` instead of a guess. 10 is what makes any of it re-checkable
— a mapping artifact that differs run to run cannot be diffed, and a lineage you
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
