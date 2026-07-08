# Sketch-based evidence layer for architecture and code audit

- **Status:** draft. Imported from a design discussion and normalized; the
  pasted original suggested an Own.NET-style `P-NNN` path, but OwnAudit keeps
  flat topic docs under `docs/`.
- **Related:** `007 docs/sketch-aware-evidence.md` (the 007-side per-run
  execution evidence this layer ingests) and
  `Own.NET docs/proposals/P-033-probabilistic-data-structures.md` (the
  in-process instrumentation whose `own.sketches.v1` exports this layer
  anticipates).

## Summary

OwnAudit should add a sketch-based evidence layer for compactly summarizing audit findings across repositories, pull requests, builds, and analyzer outputs.

The goal is to make OwnAudit better at answering questions such as:

- which files are repeatedly risky;
- which rules fire most often;
- which warnings are noise;
- which modules have unstable ownership;
- which tests are slow or flaky;
- which PRs have unusually large blast radius;
- which findings are duplicates under different wording;
- which architecture drift signals are increasing over time.

This proposal complements the existing direction where OwnAudit acts as an evidence orchestrator and audit/report/gate layer. Own.NET can produce facts. 007 can produce agent execution evidence. OwnAudit should aggregate, rank, compare, and explain.

## Problem

Architecture audits often drown in raw findings:

```text
312 warnings
48 changed files
9 analyzer categories
17 test failures
5 architecture rules
2 flaky checks
1 very tired developer
```

Raw counts are not enough. They do not explain trend, severity, repetition, blast radius, or whether the same issue keeps coming back wearing a fake mustache.

OwnAudit needs compact evidence models that can survive repeated runs and answer:

- what changed since the last audit;
- what is newly risky;
- what is chronically risky;
- what is statistically abnormal;
- what should block a gate;
- what should merely be reported;
- what should be suppressed as known noise.

## Proposed solution

Introduce a normalized evidence layer, `OwnAudit.Evidence.Sketches`.

It should support the following families of summaries.

### 1. Heavy hitters for repeated risk

Use Top-K / Space-Saving style summaries for:

- files most often changed;
- files most often involved in failed checks;
- rules most often triggered;
- symbols most often touched by refactors;
- modules most often violating architecture boundaries;
- tests most often flaky;
- dependencies most often involved in policy violations.

Example output:

```json
{
  "schema": "ownaudit.heavy_hitters.v1",
  "kind": "rule_findings_by_file",
  "top": [
    {
      "key": "src/Foo/Bar.cs",
      "estimatedCount": 31,
      "lastSeenRunId": "2026-07-06T12-00-00Z"
    }
  ]
}
```

### 2. Latency sketches for CI and analyzer timing

Use t-digest/DDSketch-like summaries for:

- analyzer execution time;
- build step duration;
- test duration;
- PR audit duration;
- report generation duration.

This lets OwnAudit report:

```text
Analyzer OWN014:
  p50: 180 ms
  p95: 2.1 s
  p99: 5.8 s
```

This matters because “the analyzer is fast on average” is how slow tools sneak into CI and start eating morale.

### 3. Bitmap indexes for audit slicing

Use bitmap or roaring-style indexes to represent sets of internal ids:

- files affected by rule X;
- files changed in PR Y;
- files owned by module Z;
- files violating architecture boundary B;
- tests covering changed files;
- findings suppressed by policy;
- findings promoted to gate failures.

Then OwnAudit can compute:

```text
GateFailures =
    ChangedFiles
    AND ArchitectureViolations
    AND NOT SuppressedFindings
```

This gives OwnAudit a compact internal query model for reports and gates.

### 4. SimHash / MinHash for finding duplicates and near-duplicates

Use fingerprints for:

- similar analyzer findings;
- repeated review comments;
- similar stack traces;
- near-duplicate architecture drift explanations;
- repeated agent mistakes from 007 (the per-run fingerprints arrive via the
  export defined in `007 docs/sketch-aware-evidence.md`);
- copy-pasted code smells.

The output should group related findings:

```json
{
  "schema": "ownaudit.similar_findings.v1",
  "groupId": "simhash:8f31...",
  "items": [
    "OWN014 in FileA.cs",
    "OWN014 in FileB.cs"
  ],
  "reason": "similar diagnostic message and nearby code structure"
}
```

### 5. Optional HLL for unique cardinality trends

Use HLL/HLL++ style sketches only where exact distinct counting is too expensive or noisy:

- unique files touched over time;
- unique rules triggered;
- unique symbols affected;
- unique contributors touching risky modules;
- unique dependency packages observed.

For most small repositories, exact sets are enough. HLL should not be added just to look sophisticated. That would be technical debt wearing a lab coat.

## Architecture

OwnAudit should treat sketches as evidence, not as final truth.

Suggested flow:

```text
raw inputs
  -> parsers
  -> normalized facts
  -> sketch aggregators
  -> audit evidence
  -> policy/gate
  -> report
```

Inputs may include:

- Own.NET analyzer facts;
- build logs;
- test results;
- Git diff metadata;
- architecture rules;
- 007 action plans and effect ledgers;
- previous OwnAudit reports.

Outputs should be stable JSON artifacts:

```text
artifacts/ownaudit/evidence/
  heavy-hitters.json
  latency-sketches.json
  bitmap-indexes.json
  similarity-groups.json
  trend-summary.json
```

## Policy integration

Sketch evidence should support policies such as:

```yaml
rules:
  - id: audit.hotspot.file_changed_too_often
    when:
      heavy_hitter:
        kind: changed_files
        min_estimated_count: 10
    severity: warning

  - id: audit.pr.large_architecture_blast_radius
    when:
      bitmap_intersection:
        left: changed_files
        right: architecture_sensitive_files
        min_count: 5
    severity: error
```

The goal is not to make OwnAudit mystical. The goal is to make repeated patterns visible and enforceable.

## MVP

The MVP should include:

1. stable evidence schema;
2. Top-K heavy hitters for:
   - files by findings;
   - rules by frequency;
   - tests by failure count.
3. simple latency summaries for audit/build/analyzer duration;
4. bitmap index abstraction for file ids and finding ids;
5. report section:
   - “Repeated hotspots”;
   - “New anomalies”;
   - “Chronic findings”;
   - “Large blast-radius changes”.

## Phase 2

Add:

- SimHash grouping for similar findings;
- trend comparison across audit runs;
- JSON schema validation;
- gate policy integration;
- ingestion of 007 run evidence;
- ingestion of Own.NET runtime diagnostic exports.

## Non-goals

OwnAudit should not:

- become a time-series database;
- store every raw event forever;
- replace Prometheus/Grafana;
- pretend approximate summaries are exact facts;
- block PRs only because a probabilistic estimate twitched;
- require Redis/Valkey to run local audit.

Approximate evidence can raise suspicion. Exact evidence should convict. Tiny difference, huge legal and engineering consequences.

## Acceptance criteria

This proposal is successful when:

- OwnAudit can identify repeated file/rule/test hotspots;
- reports show p95/p99 durations, not only averages;
- PR reports can describe blast radius using set intersections;
- similar findings can be grouped instead of repeated as spam;
- gate rules can consume sketch-derived evidence with clear thresholds;
- exported artifacts are stable enough for 007 and Own.NET integration;
- the system remains usable without external infrastructure.

## Expected benefit

OwnAudit becomes less of a static report printer and more of an evidence engine:

- better prioritization;
- clearer architecture drift signals;
- fewer duplicate findings;
- more useful PR gates;
- better historical comparison;
- stronger bridge between Own.NET facts and 007 execution evidence.

The important part: OwnAudit should not merely say “there are problems”. That is useless; everyone knows there are problems. OwnAudit should say which problems are recurring, growing, risky, and worth fixing now.