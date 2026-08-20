# SecurityInvariantMine — CVE-to-invariant mining and executable witnesses

Status: design proposal

## 0. Decision

This capability belongs in **OwnAudit**, not in the Own.NET analyzer core.

OwnAudit owns the evidence-heavy workflow: advisory ingestion, repository and revision
resolution, patch acquisition, vulnerable/fixed checkout orchestration, dynamic witness
execution, provenance, qualification, reporting, and commercial policy. Own.NET remains
the package-independent static analysis engine. It receives only reviewed, versioned
semantic predicates and their reduced regression fixtures.

The product is **not another vulnerable-package scanner**. Package/version findings are a
useful compatibility layer, but NuGet Audit, GitHub, Dependabot, OSV, Snyk, and other SCA
products already cover that market. The differentiator is the transformation:

```text
real vulnerability
  -> verified vulnerable/fixed revisions
  -> security-relevant semantic delta
  -> violated package-independent invariant
  -> candidate Own.NET predicate
  -> isolated executable witness
  -> qualified static + dynamic finding
```

A CVE is source evidence, not the final diagnostic.

## 1. Problem statement

Advisories describe concrete failures in concrete package versions. A source analyzer
needs a more general statement: what property was violated, what program facts prove the
violation, and where else can the same defect occur?

Bad output:

```text
Package X version Y is vulnerable. Upgrade it.
```

Desired output:

```text
An attacker-controlled recursive structure reaches this recursive edge, but no finite
nesting or item budget dominates the edge.
```

The second statement can detect the same defect class in application code, internal
libraries, forks, vendored code, and unrelated packages. It also survives renames and
version changes.

## 2. Scope and non-goals

### In scope

- ingest reviewed .NET/NuGet advisories and their aliases;
- resolve upstream repositories, vulnerable revisions, fixed revisions, and fix commits;
- extract and review security-relevant semantic deltas;
- classify advisories by analyzer applicability;
- derive package-independent security invariants;
- encode accepted invariants as Own.NET candidate predicates;
- build deterministic vulnerable/fixed fixtures;
- generate or reconstruct an **isolated executable witness** that demonstrates the
  property violation without targeting external systems;
- correlate static predictions with dynamic witness observations;
- preserve replayable evidence and provenance;
- measure candidate quality against vulnerable, fixed, negative, and prospective corpora.

### Non-goals

- replacing NuGet Audit, OSV, Dependabot, or general SCA;
- publishing weaponized exploits or target-specific attack automation;
- assuming every CVE can or should become a source rule;
- accepting an LLM explanation as evidence;
- running generated witnesses against public services, production data, or third-party
  infrastructure;
- moving advisory ingestion, sandbox orchestration, or commercial policy into Own.NET.

## 3. Applicability classes

Every advisory must receive exactly one primary class before rule work begins.

| Class | Meaning | Product output |
|---|---|---|
| `dependency-only` | The defect is internal to a package/runtime and does not yield a defensible source predicate for consumers | package/version finding or no rule |
| `consumer-analyzable` | Application code can misuse an API or omit a required security guard | Own.NET predicate candidate |
| `library-author-analyzable` | The library defect expresses a recurring implementation invariant | Own.NET predicate candidate |
| `configuration` | The decisive property belongs to ACLs, hosting, build, deployment, or environment | OwnAudit configuration/runtime check |
| `unknown` | Evidence is insufficient or mixed | quarantine; no rule |

`unknown` and `dependency-only` are valid outcomes. Forcing every advisory into a
diagnostic would create a noisy SAST catalogue whose main feature is being ignored.

## 4. Candidate invariant families

The first pilot should stay deliberately narrow.

### 4.1 Archive, path, and link containment

Property:

```text
Every destination derived from untrusted archive or path input remains inside the
intended root after platform-correct canonicalization and link/reparse-point handling.
```

Candidate facts include trust origin, path composition, normalization, root comparison,
filesystem write, symlink/reparse-point behavior, and time-of-check/time-of-use gaps.

### 4.2 Parser and deserializer resource budgets

Property:

```text
Attacker-controlled structural growth is bounded before it reaches recursive traversal,
allocation, expansion, or repeated parsing.
```

Candidate budgets include nesting depth, total items, bytes, expansion ratio, recursion,
work units, and wall-clock/cancellation boundaries.

### 4.3 Progress and cycle guarantees

Property:

```text
Every cycle over attacker-influenced state has a statically visible progress measure,
visited-state guard, retry bound, cancellation path, or another finite budget.
```

The predicate must reason about the failure path as well as the happy path. A cursor that
advances only under attacker-controlled conditions is not a proof of progress.

### 4.4 Local IPC and privilege boundaries

Property:

```text
A privileged operation requested over local IPC is authorized against the actual peer
identity and constrained to an explicit resource policy.
```

Candidate facts include named-pipe or socket creation, ACL/security descriptor policy,
peer authentication, predictable endpoint names, impersonation, and client-controlled
file destinations.

## 5. Pipeline

### Stage A — advisory ingestion

Initial sources:

- GitHub Advisory Database, filtered to reviewed NuGet advisories;
- `dotnet/announcements` security advisories;
- OSV for package/version/commit normalization;
- MSRC CVRF and CVE JSON for aliases, revision history, CWE, severity, and references;
- NVD only as enrichment, not as repository authority.

Normalized record:

```yaml
schema: security-invariant-candidate-v1
advisory:
  id: CVE-YYYY-NNNN
  aliases: []
  ecosystem: NuGet
  cwe: []
  references: []
affected:
  packages: []
  ranges: []
source:
  repository: null
  vulnerable_revision: null
  fixed_revision: null
  fix_commits: []
classification:
  applicability: unknown
  confidence: unreviewed
analysis:
  invariant_family: null
  invariant: null
  attacker_control: []
  security_sinks: []
  guards_before: []
  guards_after: []
evidence:
  patch_status: unresolved
  witness_status: absent
  static_status: absent
```

The raw source record and normalized record are both retained. Normalization must never
silently overwrite source disagreement.

### Stage B — repository and patch resolution

A candidate is `patch-resolved` only when all of the following are recorded:

1. canonical upstream repository;
2. vulnerable revision or a defensible vulnerable parent;
3. fixed revision;
4. fix commit or minimal ordered commit set;
5. advisory-to-patch evidence;
6. changed files and diff digest;
7. ambiguity flags for refactors, generated files, backports, and mixed fixes.

Advisory prose without a verified patch remains `metadata-only`.

### Stage C — semantic delta extraction

The unit of analysis is not a textual diff hunk. It is a change in security-relevant
program facts.

Example:

```yaml
before:
  attacker_controls:
    - nested message structure
  recursive_edge:
    - ReadValue -> ReadArray -> ReadValue
  dominating_guards: []
after:
  dominating_guards:
    - finite depth budget
  monotonic_effects:
    - depth decreases on every recursive edge
property:
  - attacker-controlled nesting cannot cause unbounded recursion
```

Deterministic extractors run first. An LLM may propose labels or explanations only after
patch facts exist, and its output remains a hypothesis until replay and review confirm it.

### Stage D — invariant derivation

An accepted invariant must be:

- independent of package and symbol names;
- stated in terms of trust, effects, control/data flow, resources, and guards;
- strong enough to reject the vulnerable revision;
- narrow enough to accept the fixed revision and realistic negative examples;
- representable as an Own.NET predicate or explicitly classified as runtime/configuration
  only;
- traceable to all supporting advisories and patches.

A single CVE may seed a provisional invariant. Promotion should normally require either:

- two independent vulnerabilities exhibiting the same invariant; or
- one vulnerability with a particularly clear patch, executable witness, and formalizable
  property.

### Stage E — Own.NET predicate candidate

OwnAudit exports a versioned candidate pack rather than directly modifying the analyzer:

```yaml
schema: own-security-predicate-v1
id: SEC-PROGRESS-001
family: progress-cycle-guarantee
sources:
  advisories: []
  patches: []
predicate:
  source_kinds: []
  required_facts: []
  forbidden_proofs: []
  accepted_guards: []
fixtures:
  vulnerable: []
  fixed: []
  negative: []
qualification:
  status: candidate
```

Own.NET may then implement the predicate with Roslyn `IOperation`, CFG, dataflow,
interprocedural summaries, and domain-specific models. The core must not know about CVE
feeds, package versions, witness containers, licensing, or billing.

## 6. Executable witness: static prediction meets dynamic proof

The analogue of OwnAudit's memory-leak tandem is:

```text
static analysis:
  identifies the source-to-sink path and missing invariant proof

dynamic witness:
  exercises a bounded, isolated input and observes the predicted security consequence

correlation:
  confirmed / static-only / runtime-only / inconclusive
```

Call this artifact an **executable witness**, not an exploit generator. The distinction is
operational, not cosmetic.

### 6.1 Witness contract

A witness must declare:

```yaml
schema: security-witness-v1
candidate_id: SEC-...
mode: vulnerable | fixed | negative
isolation:
  network: none
  filesystem: ephemeral
  privileges: unprivileged
  external_targets: forbidden
limits:
  timeout_seconds: 10
  memory_mb: 256
  process_count: 8
input:
  generator: deterministic
  seed: 0
oracle:
  expected_observation: null
  forbidden_observation: null
provenance:
  repository: null
  revision: null
  build_digest: null
  witness_digest: null
```

### 6.2 Allowed witness observations

Examples of bounded observations:

- attempted write escapes an ephemeral extraction root;
- recursion or work counter exceeds the declared budget;
- parser fails to make progress under a bounded input;
- unauthorized local client reaches a test-only privileged operation;
- resource use crosses a small deterministic threshold;
- fixed revision rejects the same input or preserves the invariant.

The harness records the observation. It must not contact external targets, persist outside
its ephemeral workspace, request elevated privileges, or produce reusable target-specific
attack automation.

### 6.3 Generation modes

Witness creation should support three modes, in descending trust:

1. **reconstruct** — adapt an upstream regression test or maintainer-provided reproducer;
2. **derive** — generate a minimal input from the verified semantic delta and test oracle;
3. **synthesize** — LLM/solver proposes a witness, then the harness independently builds,
   runs, minimizes, and validates it against vulnerable and fixed revisions.

Generated output is not accepted because it executes once. It must satisfy the complete
qualification matrix below.

### 6.4 Correlation states

| Static | Dynamic | State | Meaning |
|---|---|---|---|
| hit | reproduced | `confirmed` | strongest evidence |
| hit | not reproduced | `static-only` | environment/model gap or false positive; do not silently downgrade |
| miss | reproduced | `runtime-only` | analyzer blind spot; candidate for model expansion |
| miss | not reproduced | `inconclusive` | no useful claim |

As with runtime leak witnesses, dynamic non-reproduction never proves absence unless the
witness contract is complete for the claimed property.

## 7. Qualification gates

A candidate predicate cannot become stable until it passes all required gates.

### 7.1 Four-revision matrix

At minimum:

| Fixture | Static expected | Dynamic expected |
|---|---:|---:|
| upstream vulnerable revision | hit | reproduce |
| upstream fixed revision | clean | reject/preserve |
| reduced vulnerable fixture | hit | reproduce |
| reduced fixed fixture | clean | reject/preserve |

### 7.2 Negative and prospective evidence

Also required:

- realistic negative counterexamples;
- sibling APIs and alternate guards;
- platform and framework variants where semantics differ;
- prospective sweep over code not selected because it already had a CVE;
- false-positive review with preserved adjudication notes;
- baseline comparison within the same analysis tier.

### 7.3 Provenance and replay

Every promoted finding must preserve:

- advisory source and retrieval revision;
- repository and commit identities;
- patch digest;
- build/toolchain identities;
- static analyzer and predicate versions;
- witness source, seed, limits, and digest;
- stdout/stderr and structured observation;
- vulnerable/fixed matrix verdicts;
- reviewer decision.

The producer may claim a state, but the consumer must be able to replay the official
verifier. Prose is not a certificate.

## 8. Prior art and differentiator

This direction has substantial prior art. It must not be marketed as "nobody has ever
combined vulnerabilities and program analysis."

Existing categories include:

- SCA tools that report vulnerable package versions and fixes;
- reachability analysis that maps application call paths to vulnerable dependency code;
- SAST and IAST products that combine static and runtime evidence;
- patch-based vulnerability localization, pattern mining, automated repair, and PoC
  generation research;
- manually curated CodeQL/Semgrep-style security rules and regression suites.

The narrower proposed differentiator is the complete evidence chain:

```text
CVE/fix patch
  -> package-independent invariant
  -> reusable Own.NET semantic predicate
  -> isolated vulnerable/fixed executable witness
  -> static/dynamic correlation
  -> replayable qualification record
```

Reachability asks whether an application reaches a known vulnerable element. This project
asks whether arbitrary .NET code independently violates the same underlying security
property, even when the original package, API, and version are absent.

PoC generation asks whether a concrete vulnerability can be demonstrated. This project
uses a bounded witness as one qualification arm for a generalized analyzer predicate and
requires the same witness to distinguish vulnerable and fixed revisions.

That combination may be publishable and commercially useful, but novelty is an empirical
claim. The pilot must compare against current SCA reachability, SAST rules, IAST evidence,
and patch/PoC research before making a stronger claim.

## 9. Product and commercial boundary

A plausible split is:

### Own.NET — open analyzer engine

- stable package-independent predicates;
- local diagnostics and SARIF;
- reduced public fixtures;
- transparent rule semantics;
- no advisory-feed lock-in.

### OwnAudit Community

- local advisory ingestion for public sources;
- dependency/version compatibility findings;
- local static runs;
- limited public witness fixtures;
- replay of published qualification records.

### OwnAudit commercial layer

- continuously curated and reviewed invariant catalogue;
- private-repository mining and organization-specific predicates;
- hosted or enterprise witness execution with hardened isolation;
- cross-repository prioritization and dashboards;
- proprietary negative corpus and false-positive calibration;
- compliance evidence, retention, policy, and support;
- early-access candidate packs before open promotion.

Do not paywall the meaning of a diagnostic or make the open analyzer depend on a secret
remote verdict. Sell curation, orchestration, isolation, evidence management, enterprise
integration, and update velocity. That is a defensible product boundary; charging merely
to repeat public CVE metadata is not.

## 10. Threat model for the witness service

Treat candidate repositories, patches, builds, and generated inputs as hostile.

Required controls before hosted execution:

- disposable VM or equivalent hardened isolation boundary;
- no ambient credentials or cloud metadata access;
- deny-by-default network policy;
- unprivileged execution and no host mounts;
- immutable base image and pinned toolchain;
- CPU, memory, process, file-size, and wall-clock limits;
- separate build and run phases when practical;
- complete artifact hashing and audit trail;
- output and crash-dump review before publication;
- manual approval for new witness families;
- kill switch and per-tenant quotas.

A container alone is not a sufficient trust boundary for arbitrary generated code.

## 11. Pilot plan

### P0 — corpus and schema

- ingest 100-200 reviewed NuGet/.NET advisories from roughly the last five years;
- normalize aliases, package ranges, repositories, revisions, CWE, and references;
- classify into the five applicability classes;
- publish corpus-selection and exclusion rules;
- implement no analyzer rule yet.

Exit criterion: at least 80% of selected records have a defensible classification, and the
unresolved remainder is explicitly represented rather than discarded.

### P1 — two invariant families

Start with:

1. archive/path/link containment;
2. parser/deserializer resource budgets.

For each family:

- resolve at least two independent fixes where available;
- extract semantic deltas;
- define candidate predicates;
- build vulnerable/fixed reduced fixtures;
- compare against existing analyzers.

Exit criterion: at least one family produces a predicate that distinguishes vulnerable,
fixed, and negative fixtures without package-name checks.

### P2 — executable witness

- reconstruct one upstream regression witness;
- derive one minimal witness from a patch;
- run both under the isolation contract;
- emit `confirmed/static-only/runtime-only/inconclusive` correlation records;
- prove deterministic replay on a second clean runner.

Exit criterion: the witness distinguishes vulnerable and fixed revisions under pinned
limits and produces byte-stable structured verdicts, excluding timestamps and explicitly
listed nondeterministic fields.

### P3 — Own.NET handoff

- freeze `own-security-predicate-v1`;
- implement one candidate in Own.NET behind an experimental rule flag;
- preserve source advisory and qualification references without package coupling;
- run prospective sweep and false-positive review;
- decide promotion, revision, or rejection.

## 12. Success metrics

Do not report "CVE coverage" as though it were global recall.

Useful metrics:

- advisories by applicability class;
- patch-resolution rate;
- invariant yield: accepted families / reviewed advisories;
- independent advisories per invariant family;
- vulnerable/fixed discrimination rate;
- witness reconstruction and derivation success rates;
- static/dynamic correlation distribution;
- false-positive acceptance rate from prospective review;
- baseline comparison by analysis tier;
- lead time on historical revisions;
- cost per qualified invariant, not merely cost per ingested CVE.

The likely outcome from the first 100-200 advisories is a small number of strong invariant
families, not hundreds of rules. That is success. Five defensible predicates are more
valuable than two hundred package-shaped warnings.

## 13. Open questions

- Which advisory sources provide sufficiently stable commit linkage for the pilot?
- Should the invariant catalogue be stored beside `leakmine/` or in a separate
  `securitymine/` package?
- Which sandbox boundary is acceptable for local, CI, and hosted modes?
- When does a dynamic observation prove the intended property rather than merely crash?
- How are platform-specific invariants represented without fragmenting rule identity?
- Which portions of the curated corpus and witness artefacts can be redistributed?
- What minimum independent evidence promotes a provisional invariant?
- Should commercial candidate packs eventually become open after a defined delay?

## 14. Recommended repository shape

```text
OwnAudit/
  securitymine/
    schema.py
    ingest/
    resolve/
    classify/
    semantic_delta/
    invariants/
    witnesses/
    correlate.py
    verify.py
    tests/
  docs/
    security-invariant-mine.md
  artifacts/
    securitymine/

Own.NET/
  frontend/roslyn/
    experimental security predicates only after qualification
  corpus/security/
    reduced public vulnerable/fixed/negative fixtures
```

The first implementation PR should contain only `securitymine` schemas, deterministic
ingestion fixtures, and classification tests. Do not begin with witness synthesis or a
new analyzer rule. First prove that the corpus yields repeatable invariants rather than a
pile of vulnerability-flavoured anecdotes.
