# Verifiable computation and ZK technology radar

Status: **WATCH — do not adopt yet**  
Decision date: 2026-08-15

## Decision

OwnAudit should **not** integrate Plonky3, a zkVM, or another zero-knowledge proving stack into the current product or research pipeline.

The current evidence model is better served by deterministic recomputation, explicit provenance, canonical encodings, cryptographic digests, signatures/attestations where needed, and independently replayable witnesses. Adding a STARK proving stack where the verifier can simply rerun the computation would increase implementation and security complexity without removing a meaningful trust boundary.

Keep verifiable computation on the technology radar and revisit it only when OwnAudit has a concrete trust problem for which proof verification is materially preferable to recomputation.

## Why this is not an integrity/provenance replacement

A succinct proof can establish a mathematical claim of the form:

```text
Given public inputs P and private witness W,
program/analyzer A(P, W) produced result R.
```

It does **not** establish that `W` came from the real system we intended to observe.

In particular, a STARK or zkVM proof does not by itself prove that:

- an agent was actually sandboxed;
- a process had no network or credential access;
- a particular executable or container image was the one that ran;
- an analyzer observed the claimed source tree rather than substituted input;
- a runtime artifact originated from the claimed machine/process;
- an external producer run really occurred.

Those remain provenance/attestation problems. OwnAudit's existing rule should therefore remain intact: unknown identity or provenance is refused or represented as unknown, not inferred from a proof over supplied bytes.

The dangerous failure mode is a perfectly valid proof over dishonestly sourced input.

## Current OwnAudit fit

Most current OwnAudit computations are deliberately replayable:

```text
source / SARIF / runtime artifact
        |
        v
normalized evidence
        |
        v
typed identity + provenance
        |
        v
deterministic analysis / correlation / policy
        |
        v
result + replayable evidence
```

Where the verifier already has the evidence and can rerun the reducer or analysis cheaply, a proof system buys little. For these cases, prefer:

- canonical serialization;
- content-addressed artifacts and digests;
- signed producer/CI attestations when an external identity must vouch for origin;
- immutable or append-only evidence records where appropriate;
- reproducible execution and independent falsification.

Do not add ZK merely to make an evidence chain look more cryptographic.

## Revisit triggers

Re-evaluate verifiable computation when at least one of the following becomes a real requirement.

### 1. Verification over proprietary input without disclosure

Example: a customer wants to prove that a specific committed private repository satisfied an OwnAudit policy without disclosing the repository to the verifier.

A useful claim could look like:

```text
public:
  source_commitment
  analyzer_version
  policy_version
  result = PASS

private:
  source tree

prove:
  commitment(source tree) == source_commitment
  && OwnAudit(analyzer_version, policy_version, source tree) == PASS
```

This is a genuine ZK use case because recomputation by the verifier would require disclosure of the private input.

### 2. Privacy-preserving cross-organization research

Example: several organizations contribute committed private observations, while a public result reports only aggregate statistics under a preregistered rule.

A proof could establish that published counts/ratios were computed from the committed observations using the frozen analysis rule without revealing individual findings or repositories.

This could become relevant for studies where denominator provenance, independent atomic findings, and resistance to post-hoc reclassification matter, but it is not needed for the current local research corpus.

### 3. Untrusted outsourced expensive analysis

Example: a remote worker performs an analysis whose cost is large enough that independently repeating it defeats the purpose of outsourcing it.

Verifiable computation becomes attractive when:

```text
cost(verify proof) << cost(recompute analysis)
```

and the worker is outside the trust boundary.

This trigger must be demonstrated by measurement, not assumed because the analysis sounds expensive.

## Non-triggers

The following are **not** sufficient reasons to introduce a proving system:

- binding an artifact to a digest;
- proving that stored bytes have not changed;
- associating a finding with a producer run;
- recording source commit/configuration identity;
- proving a CI identity signed a statement;
- establishing sandbox or host isolation;
- replacing a cheap deterministic reducer;
- making a report harder to tamper with after generation.

Hashes, signatures, attestations, transparency/append-only logs, reproducible builds, and replay are simpler mechanisms for those problems.

## Plonky3 assessment

[Plonky3](https://github.com/Plonky3/Plonky3) is a modular Rust toolkit for polynomial IOP/STARK implementations rather than a drop-in application-level proof API. It exposes low-level choices including finite fields, AIR/STARK machinery, polynomial commitment schemes such as FRI/STIR, Merkle commitments, hashes, DFT/FFT implementations, lookup/sumcheck-related components, and SIMD-oriented field implementations.

That flexibility is useful when building or optimizing a proving backend. It is also exactly why Plonky3 should **not** be OwnAudit's first integration layer if a verifiable-computation experiment becomes justified.

Current upstream documentation also warns that the verifier may panic on some malformed proofs and recommends downstream integrators accepting untrusted proofs protect the verification boundary accordingly. This is a useful reminder that adopting a proof system creates a new parser/verification attack surface in addition to the mathematics.

## Preferred adoption path if a trigger fires

Use the highest-level mechanism that can test the hypothesis.

### Phase 0 — freeze the claim

Before choosing proving technology, specify:

1. the distrusted party;
2. public inputs and outputs;
3. private witness, if any;
4. the exact deterministic computation being proved;
5. how every public commitment binds to existing OwnAudit identity/provenance contracts;
6. what real-world facts remain outside the proof;
7. the expected recomputation cost and acceptable verification cost.

If this cannot be written precisely, there is no proof-system requirement yet.

### Phase 1 — prototype in a zkVM

Prefer an existing zkVM such as SP1/OpenVM-class systems for the first experiment, so the prototype can reuse ordinary deterministic program logic instead of immediately designing a custom AIR.

The first prototype should answer only whether the trust/cost/privacy hypothesis works.

### Phase 2 — benchmark against ordinary verification

Measure at minimum:

- native/recompute time;
- proof generation time;
- verification time;
- peak prover memory;
- proof size;
- artifact/setup/toolchain complexity;
- failure behavior for malformed/untrusted proofs.

A proving stack should not be adopted when verification plus operational complexity is worse than replaying the original computation.

### Phase 3 — consider direct Plonky3 only for a measured bottleneck

Move below a zkVM abstraction only if profiling shows that a specialized AIR, field, PCS, hash, or recursion design gives a material benefit needed by the use case.

Direct Plonky3 integration is therefore an optimization/backend-design decision, not the starting point.

## Adoption gate

A proposal to move this technology from WATCH to ADOPT must provide all of the following:

- a concrete trust boundary that ordinary replay does not solve economically or privately;
- a frozen statement of what the proof proves and explicitly does not prove;
- commitment binding to OwnAudit identity/provenance artifacts;
- deterministic semantics for the computation inside the proof;
- benchmark evidence showing why recomputation is insufficient;
- explicit proof-system security parameters and assumptions;
- hostile-input handling at the proof/verifier boundary;
- pinned/reproducible proving and verification toolchains;
- an end-to-end negative witness showing that a false result cannot pass merely by substituting an unbound input.

Until that gate is satisfied, ZK/verifiable computation remains research material rather than product architecture.

## Bottom line

Plonky3 is relevant to OwnAudit as a **future proving-backend option**, not as a current dependency.

The credible future uses are narrow but real: private-input verification, privacy-preserving aggregate research, and verification of expensive outsourced computation. For today's OwnAudit evidence pipeline, replayable evidence plus explicit provenance is simpler, cheaper, and addresses the actual trust boundaries more directly.
