# Finding identity — pattern, occurrence, provenance

Two identities, answering two different questions, plus the input contract that
makes the second one possible at all. Frozen by Own.NET#266 (slice 0 froze the
pattern, slice 1B added the occurrence and the provenance manifest).

| | question | contract | implementation |
|---|---|---|---|
| `pattern_id` | *which finding is this, as a pattern?* | [`finding-pattern/v1`](../contracts/finding-pattern-v1.json) | `identity/pattern.py` |
| `occurrence_id` | *which physical occurrence, in which run?* | [`finding-occurrence/v1`](../contracts/finding-occurrence-v1.json) | `identity/occurrence.py` |
| provenance | *what produced these bytes?* | `producer-provenance/v1` | `aggregate/provenance.py` |

`pattern_id` collides on purpose: two findings with the same `(path, rule,
message)` are one repeated pattern, and one judged verdict covers all of them.
`occurrence_id` is what tells those physical results apart.

Neither is the SARIF `partialFingerprints["ownAudit/v1"]`, which is a legacy
GitHub-correlation key with different rules and an `/ordinal` suffix. When
identity is exported to SARIF it goes **alongside** that key, never in place of
it — see [`docs/fp-judge/verdict-contract.md`](fp-judge/verdict-contract.md).

## The occurrence recipe, and why the gate matters more

```
preimage = b"finding-occurrence/v1\0"
         + <byte length> ":" <utf-8 bytes>     for each field, in order:
             producer_run_id, producer_name, pattern_id, path,
             start_line (canonical decimal), start_column ("null" when absent)

occurrence_id = sha256(preimage)[:32]
```

**Length-prefixed, not separator-joined.** `finding-pattern/v1` joins with a raw
`\x1f` and asserts the separator cannot occur in its fields; the assertion is
unchecked and false in principle, and it is frozen there only because every
stored overlay is keyed by those bytes. Here there is no legacy to protect, so
the ambiguity is not repeated: under a raw join, `("a", "b\x1fc")` and
`("a\x1fb", "c")` produce the *same* preimage — two different occurrences under
one id. That pair is a contract vector, and it really did collide under the
first draft of this recipe. Framing removes the question instead of forbidding a
byte in a path.

Any recipe can emit a stable-looking hex string. The contract is about refusing
to. An id is minted only when **all** of these hold:

- `producer_run_id` is known — see below, this is the one that actually blocks;
- `producer_name` is known;
- `pattern_id` is computable (path, rule, message all present);
- `path` is non-empty and `start_line` is a real 1-based line;
- the anchor is **unambiguous within that producer run**.

`producer_version`, `config_digest` and `source_commit` may all be null without
blocking anything. They describe the run; they do not identify the occurrence.

When an id is refused, the record says why, in machine-readable tokens:

| token | meaning |
|---|---|
| `occurrence-id-unavailable:producer-run-id` | no manifest entry, or an entry with no run id |
| `occurrence-id-unavailable:ambiguous-physical-anchor` | another record in the run shares this anchor |
| `occurrence-id-unavailable:start-line` | the producer reported no usable line |
| `occurrence-id-unavailable:path` | the producer reported no file |
| `physical-anchor-missing:start-column` | **degradation, not a blocker** — the anchor is line-only |

One `--sarif` input per producer name, enforced. Provenance is keyed by producer
name and a record joins to it through its `tool`, so two inputs under one name
cannot be told apart — both runs would answer to the same key. Input-instance
identity is a larger model than this slice carries, so until it exists the
duplicate is rejected rather than resolved to whichever entry survived.

### The column is nullable, and never invented

`start_column` stays `null` when the producer did not report one. Not `0`, not
`1`, and not a column recovered by re-reading the source line. Own.NET's
`Diagnostic._caret_col` does exactly that for its human-readable caret — it
pulls a name out of the message text, searches the source line for it, and falls
back to the indentation. That is a renderer heuristic; promoting it to identity
would fabricate a coordinate the analysis never computed.

A missing column is a *degradation*: a line-only anchor still identifies an
occurrence while it stays unique within the run. It becomes a blocker exactly
when it stops discriminating — two records sharing `(pattern_id, path,
start_line)` with no column are indistinguishable, and **both** get
`occurrence_id: null`.

**There is no ordinal tiebreaker and there will not be one.** An ordinal would
make identity depend on the order results happen to be emitted in, which is the
defect that disqualifies `ownAudit/v1` as an identity. The test suite proves the
property directly: reversing the results in a SARIF file changes no occurrence
id.

## `input_digest` is not a run id

SARIF carries no run identity. It is tempting to reach for the SHA-256 of the
file and call it one; that would be wrong in both directions. Two separate runs
over an unchanged tree can serialize to identical bytes, and two serializers of
one run can produce different bytes. The digest binds a manifest entry to a
file. That is all it does, and that is why it is a provenance field called
`input_digest`.

So the run identity comes from outside the SARIF, from a manifest the runner
writes as it goes:

```json
{
  "schema_version": "producer-provenance/v1",
  "inputs": {
    "own-check": {
      "producer_run_id": "audit-20260729T100000Z-3f0c1d2e4b5a6789abcdef0123456789/own-check",
      "producer_name": "own-check",
      "producer_version": null,
      "input_digest": "sha256:...",
      "config_digest": null,
      "source_commit": "..."
    }
  }
}
```

`Run-Audit.ps1` stamps the run id **before** each producer starts and writes
`artifacts/provenance.json`. Re-normalizing that same recorded run with the same
manifest reproduces the same occurrence ids — which is the whole point of not
minting a run id at normalization time, since such an id would describe the
normalization instead of the analysis. The id carries a GUID as well as a
timestamp: two audits started in the same second would otherwise share producer
run ids, and "rare" is not a property an identity contract may have.

### The runner vouches only for what it watched happen

| producer | `producer_run_id` | `source_commit` |
|---|---|---|
| own-check, run by this script, clean target tree | this run | target HEAD |
| own-check, run by this script, **dirty** target tree | this run | **null** — the analyzers read the working tree, and those bytes are not in HEAD |
| CodeQL, DB built in this run | this run | target HEAD |
| CodeQL, DB reused | this run (the *analysis* ran here) | **null** — the DB was built from a tree this run never saw |
| a pre-existing Infer# SARIF | **null** | **null** |
| a pre-existing Roslyn SARIF | **null** | **null** |

The dirty-tree row is the same rule applied one step further in: `git rev-parse
HEAD` answers on a dirty tree, and recording that answer would attribute findings
to a commit that does not contain the analyzed bytes. The check is repo-wide
rather than scoped to the target subtree — over-nulling costs a nullable field
that blocks nothing, while under-nulling asserts something false.

Infer# and Roslyn are produced by separate runners, possibly yesterday, possibly
against another commit and another configuration; `Run-Audit.ps1` only *finds*
their SARIF in `artifacts/`. Stamping those with the current run id and the
current HEAD would be provenance about an analysis nobody observed — the exact
fabrication this contract exists to prevent. They get `producer_name` and
`input_digest`, which are facts about the bytes on disk, and their occurrence ids
stay null until `Run-Infersharp.ps1` / `Run-Roslyn.ps1` emit their own sidecars.

Four rules the normalizer enforces:

1. **Read metadata, never invent it.** No manifest entry means no run id means no
   occurrence id, said out loud in `identity_limitations`.
2. **Verify the digest of the exact file read.**
3. **A mismatch is rejected (exit 2), not degraded.** Falling back to "unknown
   run" would turn a wrong manifest into a slightly emptier report, and nobody
   investigates a slightly emptier report.
4. **Missing fields stay explicitly null**, so a consumer reads "we do not know"
   rather than inferring "there is no such thing".

An `input_digest` that is present and matches sets `digest_verified: true`; an
entry with no digest leaves it `false`. The two are not the same and the payload
does not blur them.

`producer_version` is the one field the resolver will fill in from the SARIF
itself when the manifest stayed quiet — a version the tool states in its own
driver must not be reported as unknown. `producer_version_source` records which
it was (`"manifest"` | `"sarif-driver"` | `null`), because "the runner asserted
it" and "the tool said so" are different claims.

The manifest is type-checked on read: an entry that is not an object, or a
`producer_run_id` that arrives as a number, raises `ProvenanceError` rather than
surfacing as an `AttributeError` far from the cause — or worse, being `str()`-ed
into a plausible-looking run identity that no producer ever emitted.

## What the recorded corpus actually looks like

Measured over `sts_audit/*.sarif` rather than assumed:

| producer | results | with `startColumn` | version in SARIF |
|---|---:|---:|---|
| own-check | 613 | **0** | — |
| codeql | 9 634 | 9 634 | `2.25.6` |
| infersharp | 207 | 207 | — |
| roslyn | 64 064 | 62 943 | — |

own-check reports no column at all. That turns out to cost almost nothing: run
the corpus through the normalizer with a manifest and **72 536 of 72 559 records
(99.97 %) earn an occurrence id**, all 380 own-check findings among them,
because their line-only anchors are unique. The 23 that do not are *column-bearing*
collisions — 12 CodeQL, 11 Roslyn — where the column was present and simply did
not discriminate.

So the missing column is a precision problem, not the thing standing between
this corpus and occurrence identity. The thing standing in the way is run
identity: the recorded STS SARIF predates the provenance contract, so it has no
manifest and every `occurrence_id` in `sts_audit/findings.json` is honestly
`null`. That is a legacy boundary, not a schema defect — those runs really cannot
be identified after the fact, and a report that claimed otherwise would be making
it up.

## Payload shape

`schema_version: "normalized-findings/v2"`. `v1` is the retroactive name for the
unversioned ten-field record that slice 1A froze; v2 adds four fields on top of
those ten and changes none of them:

```jsonc
{
  "tool": "own-check", "path": "...", "line": 72, "rule": "OWN001",
  "category": 2, "category_name": "subscription-leak", "resource": "subscription token",
  "suppressed": false, "suppress_reason": "", "message": "...",   // the ten v1 fields

  "pattern_id": "ccacc4decc1c4c12",
  "occurrence_id": null,
  "physical_anchor": {"path": "...", "start_line": 72, "start_column": null},
  "identity_limitations": ["occurrence-id-unavailable:producer-run-id",
                           "physical-anchor-missing:start-column"]
}
```

Provenance is a top-level map keyed by producer name, not a copy inside every
record: the six fields are identical for all of a producer's findings, and
duplicating them across 72 559 records would multiply the payload for no
information. Each record's `tool` is the join key.

`aggregate/tests/test_normalize.py` proves the "adds only" claim mechanically:
it projects a v2 payload back down to v1 and diffs it against the slice-1A
golden — which was generated by the *reference* implementation and is never
regenerated from the code under test.

## Still open

- **Own.NET does not record a source column.** A producer-enablement slice
  should carry a real span from the Roslyn syntax location through
  `Finding`/`Diagnostic` into SARIF `startColumn` — not reuse `_caret_col`. It
  improves anchor precision, IDE/GitHub positioning, and telling several findings
  on one line apart. It does not define the schema, so it does not block it.
- **Locationless results** are dropped and counted nowhere — [#57](https://github.com/PhysShell/OwnAudit/issues/57).
- **`lineage_id`** (following one finding across runs) is slice 2, and needs
  occurrence identity to exist first.
