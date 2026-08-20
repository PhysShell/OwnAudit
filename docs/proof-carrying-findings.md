# Proof-carrying findings in OwnAudit

- **Status:** draft design. No certificate-aware normalization, verification
  metadata, SARIF properties, or dashboard support is implemented yet.
- **Producer proposal:**
  [`PhysShell/Own.NET P-035 — Proof-carrying findings`](https://github.com/PhysShell/Own.NET/blob/main/docs/proposals/P-035-proof-carrying-findings.md)
- **Boundary:** Own.NET owns certificate semantics and the verifier. OwnAudit
  consumes, preserves, compares, and presents the result. It must not grow a
  second proof kernel or reconstruct derivations from prose evidence.

## Summary

Own.NET may eventually emit selected deterministic findings with a replayable
derivation certificate. The certificate states, in a closed versioned rule
vocabulary, how the diagnostic conclusion follows from the canonical facts
analyzed by Own.NET. A small independent verifier accepts or rejects that
certificate.

OwnAudit should treat this as a stronger evidence layer attached to an ordinary
canonical finding:

```text
Own.NET canonical facts
        ↓
finding + evidence + certificate
        ↓
Own.NET verifier result (producer metadata)
        ↓
OwnAudit normalization and optional replay
        ↓
baseline / diff / SARIF / markdown / dashboard
```

The user-facing claim must remain precise:

> **verified derivation over canonical facts**

not:

> **formally proven bug in arbitrary C#**

The latter would require a much larger trusted boundary including the C# and CLR
semantics, Roslyn extraction, reflection, generators, weaving, and runtime
assumptions. A badge should clarify evidence, not teach marketing to hallucinate
in mathematical notation.

## Repository boundary

### Own.NET owns

- `own/derivation/*` certificate schemas;
- primitive rule vocabularies such as `own.progress/v1`;
- canonical fact and symbol handles used by certificates;
- certificate construction;
- the independent verifier/kernel;
- verifier fixtures and corruption tests;
- the binding between an accepted conclusion and a canonical finding;
- Python/Rust parity for verified conclusions.

### OwnAudit owns

- ingesting certificate-bearing findings;
- preserving content-addressed or inline certificate references;
- recording producer verification metadata;
- optionally invoking the official pinned verifier for consumer-side replay;
- normalization without flattening the derivation;
- baseline/diff semantics;
- SARIF properties and attachments;
- markdown and dashboard rendering;
- triage overlays and reviewer workflow;
- optional later correlation with runtime evidence.

### OwnAudit explicitly does not own

- deriving certificates from `codeFlows`;
- reimplementing primitive proof rules in Python/C#;
- accepting a certificate because the producer wrote `verified: true`;
- repairing malformed certificates;
- inventing fallback semantics for unknown rule vocabularies;
- promoting heuristic findings to “verified” through cross-tool agreement.

Cross-tool agreement, runtime confirmation, and verified derivation are distinct
signals. Combining them can increase confidence, but none should be renamed to
impersonate another.

## Canonical finding extension (direction, not frozen schema)

A normalized finding may carry:

```json
{
  "rule": "PRG001",
  "category": "non-progress-loop",
  "path": "Parser.cs",
  "line": 84,
  "resource": "reader.Position",
  "message": "loop can repeat without progress",
  "evidence": [],
  "flow": [],
  "derivation": {
    "schema": "own/derivation/v1",
    "rule_vocab": "own.progress/v1",
    "facts_digest": "sha256:...",
    "certificate_digest": "sha256:...",
    "artifact": "derivations/sha256-....json",
    "producer_verification": {
      "status": "valid",
      "verifier": "owen-verify",
      "verifier_version": "0.x",
      "conclusion_digest": "sha256:..."
    },
    "consumer_verification": {
      "status": "valid",
      "verifier": "owen-verify",
      "verifier_version": "0.x",
      "verified_at": "2026-07-14T00:00:00Z"
    }
  }
}
```

The shape above is illustrative. Before implementation, OwnAudit and Own.NET
must freeze one canonical producer contract. The audit side should not infer
field meaning from whichever JSON happened to arrive first.

## Verification states

OwnAudit needs a closed state model. At minimum:

| State | Meaning | Presentation |
|---|---|---|
| `verified` | official verifier accepted the certificate against the bound facts | show verified-derivation badge |
| `invalid` | verifier understood the schema and rejected it | prominent pipeline error; never show as verified |
| `unverified` | certificate absent or replay not requested | ordinary finding; no badge |
| `unsupported` | consumer does not understand schema or vocabulary | ordinary finding + compatibility warning |
| `missing-artifact` | finding references a certificate that is unavailable | pipeline integrity warning |
| `digest-mismatch` | facts/certificate/conclusion digest does not bind to the finding | pipeline integrity error |

`invalid`, `missing-artifact`, and `digest-mismatch` should remain distinct. A
missing ZIP entry is not a false theorem, and an old consumer is not a malicious
producer. Good pipelines preserve the difference instead of collapsing every
unpleasant event into “something went wrong”.

## Ingest policy

### Default report behavior

- An ordinary finding without a certificate remains valid audit input.
- A certificate-bearing finding is never called verified solely from producer
  metadata.
- When the official verifier is available and compatible, OwnAudit should replay
  the certificate before displaying the verified badge.
- If replay is disabled for performance or packaging reasons, display producer
  status as `producer-claimed-valid`, not `verified`.
- Invalid certificates remain visible as pipeline-integrity failures and should
  not silently degrade to ordinary findings.
- Unsupported schemas may degrade to ordinary findings, but the compatibility
  loss must remain observable in the report metadata.

### Gate behavior

The initial rollout should not gate application code on certificate presence.
Certificate integrity may gate the audit pipeline itself:

```text
finding has no certificate          -> normal
certificate valid                   -> normal + verified signal
certificate unsupported             -> warning / observable degradation
certificate missing or digest bad   -> audit pipeline error
certificate understood but invalid  -> audit pipeline error
```

A bad certificate indicates a producer/verifier/transport defect. It is not
reasonable to punish the application developer by pretending their source code
created the broken proof artifact, but the audit run must fail loudly enough
that nobody publishes the badge.

## Artifact storage

Two storage modes are plausible.

### Inline

The certificate lives inside the canonical finding JSON.

Advantages:

- single portable artifact;
- simple local debugging;
- no missing sidecars.

Costs:

- report JSON can become large;
- repeated premises may duplicate heavily;
- SARIF embedding may become grotesque, which is a technical term meaning
  “someone will eventually open a 400 MB file in a browser”.

### Content-addressed sidecar

The finding carries a digest and relative artifact path:

```text
out/
  findings.json
  findings.sarif
  derivations/
    sha256-a1b2....json
    sha256-c3d4....json
```

Advantages:

- deduplication;
- independent retention policy;
- easier verifier replay and caching;
- SARIF can carry a digest/reference rather than the full proof object.

Costs:

- transport integrity and missing-artifact handling;
- archive/upload tooling must preserve the directory.

Leaning: canonical normalized findings carry metadata plus a content-addressed
sidecar. Small fixtures may remain inline for tests. Measure real certificate
sizes before freezing the policy.

## SARIF mapping

The existing human evidence path should continue to map to
`relatedLocations` and `codeFlows`. The derivation certificate is additional
machine evidence, not a replacement.

Suggested SARIF result properties:

```json
{
  "properties": {
    "own.derivation.status": "verified",
    "own.derivation.schema": "own/derivation/v1",
    "own.derivation.ruleVocabulary": "own.progress/v1",
    "own.derivation.certificateDigest": "sha256:...",
    "own.derivation.factsDigest": "sha256:...",
    "own.derivation.conclusionDigest": "sha256:...",
    "own.derivation.verifier": "owen-verify 0.x"
  }
}
```

Do not paste a large certificate into `properties`. Prefer an artifact reference
or report bundle sidecar. GitHub code scanning is a finding UI, not a proof
assistant wearing a web form as a disguise.

The report renderer must test that:

- the primary location matches the certified conclusion anchor;
- evidence/codeFlow handles are consistent with certificate handles;
- no empty artifact URIs are emitted;
- moving source lines does not change the semantic finding fingerprint;
- unsupported derivations do not erase ordinary evidence.

## Markdown and dashboard presentation

A finding card may show:

```text
PRG001  loop can repeat without progress
Status: new
Derivation: verified (own.progress/v1, owen-verify 0.x)
Measure: reader.Position

Evidence:
  guard reader.Position < reader.Length
  -> TryReadNode returned false
  -> continue
  -> back-edge
  -> reader.Position unchanged

Verified rule chain:
  FACT.LOOP_GUARD
  SUMMARY.OUTCOME_PROGRESS(false = never)
  CFG.BRANCH
  CFG.BACKEDGE_NO_EXIT
  PRG001.INTRO
```

The default view should show the status and compact rule chain. Full certificate
JSON belongs behind an expandable/download link. Reviewers need confidence and
navigable evidence, not an unsolicited dissertation from a serializer.

Dashboard filters should include:

- derivation status;
- rule vocabulary;
- verifier version;
- diagnostic family;
- new/baselined/triaged state;
- producer-only versus consumer-replayed verification.

## Baseline and fingerprint semantics

Certificate presence must not create a second logical finding. Baseline identity
continues to describe the defect conclusion, not the representation used to
justify it.

Therefore:

```text
same semantic finding, no certificate -> certificate added
```

is an **evidence upgrade**, not a new application defect.

Recommended diff dimensions:

- `finding_state`: new / existing / resolved;
- `derivation_state`: added / removed / unchanged / changed / invalid;
- `verification_state`: upgraded / downgraded / incompatible.

Examples:

```text
existing OWN014, derivation unverified -> verified
  finding diff: unchanged
  evidence diff: upgraded

existing PRG001, certificate digest changed but conclusion digest unchanged
  finding diff: unchanged
  evidence diff: changed; replay required

existing DI001, verified -> certificate missing
  finding diff: unchanged
  evidence diff: downgraded; integrity warning
```

A line move must not change the finding fingerprint. Certificate digests may
change when canonical CFG handles change, but that should not automatically
manufacture a “new bug”.

## Triage and confidence

Existing triage states (`real`, `uncertain`, `judged_fp`, `unjudged`) remain
human judgments about whether the finding corresponds to a defect in the real
program.

A verified derivation establishes only that the conclusion follows from the
canonical facts under the versioned rule vocabulary. It does not prove that the
frontend facts are complete or that project-specific modeling assumptions are
correct.

Consequently, this combination is possible and meaningful:

```text
derivation: verified
triage: judged_fp
reason: project model declares the event source process-long, but deployment
        replaces it per document session
```

That case should be investigated as a modeling/frontend problem, not hidden as a
logical impossibility. Proof objects are unusually good at locating which layer
deserves blame, provided nobody treats the word “verified” as holy water.

## Cross-signal confidence

OwnAudit may combine independent signals in reporting, while preserving their
identity:

| Signal | Establishes |
|---|---|
| verified derivation | conclusion follows from canonical facts and rules |
| cross-tool agreement | another analyzer reported compatible evidence |
| runtime confirmation | behavior was observed in an executed scenario |
| human triage | reviewer accepted/rejected the real-world defect claim |

A future confidence summary may say:

```text
High confidence:
- derivation verified
- runtime stack repeatedly observed at certified loop
- human triage = real
```

It must not merge these into a single opaque score that prevents reviewers from
seeing why confidence is high.

## Proposed delivery slices

### Slice 0 — consumer contract checkpoint

Blocked on Own.NET freezing:

- certificate envelope;
- verification result shape;
- stable conclusion binding;
- artifact/digest rules;
- the first rule vocabulary (`own.progress/v1`).

OwnAudit can prepare fixtures, but production parsing must not guess the
producer schema.

### Slice 1 — normalization and integrity

- accept certificate metadata on canonical findings;
- preserve inline/sidecar artifacts;
- check file presence and digests;
- model closed verification states;
- leave existing reports byte-for-byte unchanged when no derivation exists.

### Slice 2 — official verifier replay

- invoke the official pinned Own.NET verifier as a subprocess/library boundary;
- record verifier version and structured result;
- fail pipeline integrity on invalid/mismatched artifacts;
- never reimplement rules locally.

### Slice 3 — SARIF and markdown

- preserve existing `relatedLocations` and `codeFlows`;
- add compact derivation properties;
- render verification badge and compact rule chain;
- add downloadable/expandable certificate artifact.

### Slice 4 — baseline, diff, dashboard

- separate finding diff from evidence/verification diff;
- add filters and evidence-upgrade/downgrade reporting;
- integrate with existing FP-judge overlay;
- measure artifact size and replay time on a real audit run.

### Slice 5 — runtime correlation (later)

For selected rules, correlate runtime artifacts with the certified conclusion
anchor. Example: a verified `PRG001` plus repeated stack samples at the same loop
may be rendered as `runtime-confirmed-progress-stall`.

This is a separate scope. Do not attach a profiler to the first certificate PR
because “while we are here” remains one of software engineering's least funny
threats.

## Acceptance contract

1. A canonical finding without a derivation remains unchanged through all
   existing report paths.
2. A valid certificate artifact survives normalization with schema, vocabulary,
   digests, verifier metadata, and conclusion binding intact.
3. Missing artifact, digest mismatch, invalid certificate, unsupported schema,
   and unverified state remain distinguishable.
4. OwnAudit never marks producer metadata alone as consumer-verified.
5. Consumer replay uses the official verifier and contains no duplicate rule
   implementation.
6. An invalid understood certificate fails the audit integrity check and is
   never rendered with a verified badge.
7. SARIF retains existing `relatedLocations` and `codeFlows` and adds compact
   derivation metadata without embedding an unbounded proof object.
8. Markdown/dashboard can display a compact rule chain and expose the full
   artifact separately.
9. Adding a certificate to an existing finding is an evidence upgrade, not a new
   finding.
10. Line movement does not change the semantic finding fingerprint.
11. `judged_fp` findings may retain verified derivations and remain explainable
    as modeling/frontend disagreements.
12. Report output remains deterministic under artifact enumeration order.
13. Existing reports remain byte-for-byte unchanged when no derivation fields
    are present, except for explicitly versioned metadata where unavoidable.
14. Artifact size and replay cost are measured before enabling consumer replay
    by default.

## Non-goals

- owning or forking the certificate verifier;
- defining proof semantics independently from Own.NET;
- replacing ordinary findings, evidence, or `codeFlows`;
- requiring certificates for every diagnostic;
- treating missing certificates as application failures;
- turning cross-tool agreement into a fake proof;
- declaring verified findings immune to human false-positive judgment;
- embedding large derivation blobs directly in SARIF by default;
- implementing runtime confirmation in the first slice;
- advertising “formally proven C# bugs” from certificates over extracted facts.

## Open questions

1. **Verifier packaging:** invoke the `Owen.Cli` tool, ship a small dedicated
   verifier executable, or expose a stable library? Leaning: dedicated bounded
   verifier executable with JSON input/output.
2. **Producer and consumer replay:** retain both results or only consumer replay?
   Leaning: retain both for debugging transport and version skew.
3. **Retention:** keep all certificates, only new findings, or only verified
   findings? Measure artifact volume on STS and OSS corpus runs first.
4. **SARIF artifact reference:** URI into the report bundle, attachment metadata,
   or properties-only digest? Select based on GitHub/Azure DevOps viewer behavior,
   not theoretical elegance.
5. **Evidence diff UX:** should an evidence downgrade block a PR even when the
   underlying finding is baselined? Leaning: audit-integrity gate yes for invalid
   or missing required artifacts; report-only for ordinary verified → unverified
   compatibility downgrade during rollout.
6. **Verifier version skew:** whether a newer verifier may replay an older
   vocabulary must be explicitly specified by Own.NET. OwnAudit must not infer
   compatibility from semantic version vibes.

## Design source

The producer architecture is documented in Own.NET P-035. Its immediate
inspiration is Jan Mas Rovira's
[well-typed Hilbert proof eDSL](https://blog.janmasrovira.org/blog/hilbert-edsl/):
a human-friendly derivation compiles to a smaller primitive proof object checked
by an independent trusted mechanism. OwnAudit's role is the unglamorous but
necessary downstream half: preserve the object, replay it with the official
kernel, and present the result without sanding away the trust boundary.