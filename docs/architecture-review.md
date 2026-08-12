# OwnAudit architecture review, drift gate & report pipeline

- **Status:** draft. Imported from a design discussion and normalized.

## Summary

Introduce an OwnAudit-side architecture review pipeline that consumes architecture facts from Own.NET, applies reporting/baseline/drift logic, and emits PR-friendly architecture reports, SARIF, and gate verdicts.

OwnAudit should not own the extractor or analyzer core. That belongs in Own.NET. OwnAudit owns:

- consuming `arch-facts.json` and `arch-findings.json`;
- baseline and diff for architecture findings;
- architecture drift snapshots;
- PR markdown reports;
- SARIF export;
- dashboard integration;
- risk scoring;
- report-only high-level review summaries.

This proposal turns the existing `arch/` work into a product-shaped pipeline.

## Existing groundwork

OwnAudit already has an architecture roadmap that positions the project as an auditor built from semantic code graph, architecture rules, WPF/runtime probes, baseline/diff, SARIF/GitHub reports, and an AI explanation layer.

The roadmap explicitly says this is not a greenfield rewrite: OwnAudit already has findings, CLI orchestration, baseline/diff concepts, graph/dashboard artifacts, history, tiers, gates, and local smells; the real gap is cross-cutting architecture rules.

OwnAudit already contains `arch/drift.py`, which compares structure between graph snapshots and reports coupling movement, new dependency edges, and newly introduced cycles before those necessarily become hard rule violations.

OwnAudit already has `arch/rules.json` with concrete architecture rules: UI reaching SQL/data layer, Domain depending on WPF/presentation framework, cycle detection, god-class thresholds, coupling rules, and drift-sensitive targets such as SQL/WPF/DevExpress.

The roadmap also documents Phase 3 as an architecture pass over Roslyn-generated `graph.json`, with Python-side evaluation producing findings in the same `findings.json` schema for SARIF/diff/dashboard reuse.

Related docs:

- [agentic-coding-discipline-proposal.md](agentic-coding-discipline-proposal.md)
  This doc adds a design note on disciplined agentic coding, task contracts, negative prompts, plan-then-build, diff policy gates, judge-run, and trust levels for Own.NET/OwnAudit/007.

- 007 `docs/agentic-coding-discipline-proposal.md`
  This is relevant because it records the 007-side isolate → run → gate → harvest loop and future task/diff-policy gates that OwnAudit can depend on instead of reinventing agent execution.

## Problem

OwnAudit has the right pieces, but architecture review is currently split across:

- rules;
- drift diff;
- baseline/diff;
- graph docs;
- dashboard generation;
- future SARIF/reporting integration.

The missing product slice is a single command that answers:

What architectural debt exists?
What changed in this PR?
What is newly blocking?
What is old/baselined?
What is high-risk but report-only?
What should a reviewer look at first?

Without this, developers still need to read raw JSON or multiple partial reports. That is how useful analysis dies: not because the detector is wrong, but because the output is a filing cabinet thrown down a staircase.

## Proposed command surface

Add:

```bash
python3 -m arch.review_cli \
  --facts arch-facts.json \
  --findings arch-findings.json \
  --rules arch/rules.json \
  --baseline architecture-baseline.json \
  --drift-baseline arch-snapshot.main.json \
  --out-dir arch/out \
  --gate-level error
```

Outputs:

```text
arch/out/
  architecture-review.md
  architecture-findings.sarif
  architecture-findings.json
  architecture-drift.json
  architecture-drift.md
  architecture-verdict.json
  architecture-summary.json
```

## Pipeline

```text
Own.NET arch facts/findings
        ↓
OwnAudit normalization
        ↓
baseline/diff
        ↓
drift snapshot comparison
        ↓
risk scoring
        ↓
SARIF + markdown + dashboard artifacts
        ↓
gate verdict
```

## Inputs

### `arch-facts.json`

Produced by Own.NET.

Contains project/type/component dependency graph.

### `arch-findings.json`

Produced by Own.NET `Own.Arch` (see `Own.NET docs/proposals/P-032-own-arch-facts.md`).

Contains deterministic architecture findings with fingerprints.

### `architecture-baseline.json`

OwnAudit-owned artifact for accepted historical findings.

Purpose:

- allow adoption in dirty legacy codebases;
- fail only on new violations;
- force explicit reason when accepting new debt.

### `arch-snapshot.main.json`

OwnAudit-owned drift snapshot.

Used to compare current PR structure against main.

The existing drift design already treats snapshots as compact summaries containing component metrics, dependency surface, and cycles.

## Report model

The architecture review report should have five sections.

1. Verdict

```text
FAIL: 2 new blocking architecture violations.
WARN: 3 medium-risk drift items.
INFO: 1 dependency removed.
```

2. New blocking findings

Only findings that are:

- deterministic;
- not present in baseline;
- severity at or above gate level.

Example:

```text
ARCH001: Presentation depends on Infrastructure directly
Evidence:
  Broker.Presentation -> Broker.Infrastructure
  source: Broker.Presentation.csproj ProjectReference

Why this matters:
  Presentation can bypass Application policies and reach persistence implementation directly.
```

3. Baselined debt

Existing violations remain visible but do not block.

Example:

```text
ARCH-DOMAIN-WPF: 7 existing findings
Baseline reason:
  legacy ViewModel formatting leaked into Domain; tracked separately
```

4. Drift since main

Use existing `arch.drift` concepts:

- new dependency;
- removed dependency;
- new cycle;
- resolved cycle;
- coupling increase;
- instability shift.

Example:

```text
High: new dependency Sts.Domain.Orders -> System.Data.SqlClient
Medium: Sts.UI.ViewModels Ce 21 -> 27 (+6, +29%)
Info: removed dependency Sts.Legacy.Import -> DevExpress.Xpf
```

5. Recommended reviewer focus

This section is report-only and may be generated from deterministic evidence.

Example:

```text
Reviewer focus:
1. The PR introduces a new Domain -> SQL dependency.
2. The PR increases UI ViewModel outgoing dependencies by 29%.
3. No new cycles were introduced.
```

## Gate policy

Default gate behavior:

error: fail on new deterministic architecture findings
high drift: fail only if configured
medium drift: report-only by default
heuristics: report-only by default
LLM review text: never gates directly

Example:

```json
{
  "schema": "own.audit.arch.verdict/v1",
  "verdict": "fail",
  "blocking": [
    {
      "kind": "finding",
      "rule": "ARCH001",
      "fingerprint": "sha256:..."
    }
  ],
  "nonBlocking": [
    {
      "kind": "drift",
      "risk": "medium",
      "detail": "Sts.UI.ViewModels Ce 21 -> 27"
    }
  ]
}
```

## SARIF export

OwnAudit should convert architecture findings to SARIF with:

- rule id;
- severity;
- fingerprint;
- source evidence;
- help text;
- baseline status if available.

Only deterministic findings should become code scanning alerts by default.

Drift items can be added as SARIF notes later, but they should start as markdown/report artifacts. Drift often describes component-level movement rather than a single source span.

## AI explanation layer

The AI layer must be downstream of deterministic results.

Allowed AI tasks:

- summarize top architecture risks;
- explain why a rule matters;
- group repeated violations by root cause;
- propose refactoring steps;
- produce PR review text;
- suggest candidate 007 tasks.

Forbidden AI tasks:

- invent new blocking findings without analyzer evidence;
- change gate verdict;
- update baseline automatically;
- suppress architecture findings without explicit reason;
- treat style inference as deterministic truth.

## Example report

```markdown
# Architecture Review

Verdict: FAIL

## Blocking new violations

### ARCH001: Presentation depends on Infrastructure

Evidence:
- `Broker.Presentation` -> `Broker.Infrastructure`
- source: `Broker.Presentation.csproj`

Impact:
Presentation can bypass Application and directly depend on persistence implementation.

Suggested refactor:
Introduce an Application service or port and move the concrete Infrastructure dependency behind it.

## Drift since main

- High: new dependency `Sts.Domain.Orders` -> `System.Data.SqlClient`
- Medium: `Sts.UI.ViewModels` efferent coupling `21 -> 27`
- Info: removed dependency `Sts.Legacy.Import` -> `DevExpress.Xpf`

## Baselined debt

- 7 existing `ARCH-DOMAIN-WPF` findings remain unchanged.
```

## Dashboard integration

Extend existing dashboard artifacts with an Architecture tab:

```text
Architecture
  - verdict
  - new blocking findings
  - total baselined debt
  - drift count by risk
  - top risky components by Ce growth
  - cycles introduced/resolved
```

No new dashboard model should be invented if existing `viz/` history/report artifacts can be reused.

## Integration with 007

OwnAudit should emit machine-readable candidate tasks for 007.

Example:

```json
{
  "schema": "own.audit.arch.task-candidates/v1",
  "tasks": [
    {
      "task_id": "ownarch.fix.arch001.presentation-infrastructure",
      "finding_rule": "ARCH001",
      "finding_fingerprint": "sha256:...",
      "recommended_prompt_module": "ownarch.fix-layer-violation",
      "risk": "high",
      "constraints": {
        "max_files_changed": 5,
        "require_reaudit": true,
        "forbid_baseline_update": true
      }
    }
  ]
}
```

007 remains responsible for executing/refactoring. OwnAudit only prepares evidence and gates.

## P-038 boundary-transition witness overlay

P-038 is an **accepted experiment**, not an adopted product. Own.NET supplies architecture coordinates and static boundary-site facts; OwnAudit owns the downstream join, classification, baseline/diff, and report surface.

The overlay is deliberately separate from architecture verdicts:

- it adds no coverage semantics to Own.Arch evaluation;
- it emits no `ARCH###` finding codes;
- it cannot change an architecture-gate verdict;
- nothing from it enters `rules.yaml`, the architecture baseline ratchet, or the Own.Arch evaluator.

The primary report unit is a statically resolved in-process executable call site. For each site, the overlay may show:

```text
static_test_proxy:
  likely_witnessed | likely_unwitnessed | indeterminate

runtime_observation:
  observed | not_observed | indeterminate
```

Runtime evidence is optional and belongs to the later executed tier. A runtime-only transition that cannot be matched to a static `site_id` is retained as disagreement evidence with `site_match = runtime_only`; ambiguous joins remain `ambiguous`. Neither is forced onto a static site, and neither enters P-038's primary site-level estimand.

`not_observed` is admissible only when the observation contract proves the camera was on: the site was instrumented, the collector supports the transition kind, the full declared green-suite domain completed, collection had no event loss, and per-test attribution is unambiguous. Otherwise the overlay must say `indeterminate`. Sampling collectors can establish `observed` only.

The report must preserve provenance rather than collapse the experiment into a scalar. At minimum, a runtime record binds source revision, edge/site identity where available, test identity, collector identity/version, transition kind, attribution mode, completeness, and event-loss state. This allows the report to expose concentration such as many boundary sites depending on one end-to-end test instead of pretending a ratio solved Goodhart.

For the ratified experiment, the primary estimand is limited to statically resolved in-process call sites for which the local comparator vector is defined, the full green suite is observed, collector completeness is established, and per-test attribution is admissible. `runtime_only`, `ambiguous`, and `indeterminate` rates are reported as external-validity / attrition diagnostics.

The experiment's result vocabulary is independent of the architecture verdict:

```text
POSITIVE      — useful additional association supported by the preregistered rule
NEGATIVE      — every effect at or above the useful-effect floor is excluded
INCONCLUSIVE  — the instrument/data cannot adjudicate
CLOSED        — decision record after a failed calibration/funding path, or a genuine NEGATIVE result
```

`INCONCLUSIVE` never means negative. A failed P-038 path remains a decision record rather than disappearing, so a negative result is not re-derived later as a fresh idea.

Before executed outcomes are inspected, the run must preregister the useful-effect floor, matched-strata estimator and comparator coding, precision/equivalence procedure, separation handling, differential-indeterminacy threshold, adversarial missingness assignment, and the primary-estimand population. Until then this section is a reporting contract for an experiment, not implementation authority.

## Acceptance criteria

MVP is accepted when:

1. `arch.review_cli` consumes `arch-findings.json`, optional baseline, and optional drift snapshot.
2. It emits `architecture-review.md`.
3. It emits `architecture-verdict.json`.
4. It can fail with exit code `2` on new blocking deterministic architecture findings.
5. It can run in report-only mode.
6. It integrates with existing baseline/diff conventions.
7. It reuses existing `arch/drift.py` output instead of duplicating drift logic.
8. It emits SARIF for deterministic architecture findings.
9. Tests cover:
   - clean architecture report;
   - new blocking finding;
   - baselined finding;
   - new high-risk drift;
   - report-only medium drift;
   - no baseline file;
   - malformed facts/findings input.

P-038 does **not** add acceptance criteria to this MVP. Its overlay remains experimental until its own calibration/funding/adjudication ladder produces evidence for adoption.

## Risks

Risk: architecture review becomes generic lint soup

Mitigation: only include findings with architectural evidence. Complexity, dead code, coverage, and formatting belong elsewhere. P-038 is explicitly a separate experimental overlay and cannot alter the architecture verdict.

Risk: drift becomes noisy

Mitigation: drift gates are opt-in and thresholded. Default is report-only except for high-risk sensitive-target dependencies.

Risk: AI summary overclaims

Mitigation: every AI-generated claim must cite a deterministic finding, drift item, metric, or explicitly scoped P-038 evidence record. No evidence, no claim.

## First implementation slice

Implement:

```text
arch/review_cli.py
arch/report.py
architecture-review.md renderer
architecture-verdict.json
SARIF export for deterministic arch findings
tests
```

Do not implement the P-038 runtime collector or make its overlay part of this first slice. First make the boring architecture pipeline work. Then let the experiment earn any additional implementation cost with data.
