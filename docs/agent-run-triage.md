# Agent-run triage — 007's Zero Trust audit trail as an evidence source

Status: design note / vision, not implementation (same status as
[`audit-data-leverage.md`](audit-data-leverage.md) and
[`own-net-auditor.md`](own-net-auditor.md)). Trigger to build: once **007**
actually emits structured per-run capability events (its Phase 1 — see
[`007/docs/zero-trust-framework.md`](https://github.com/PhysShell/007/blob/main/docs/zero-trust-framework.md)).
Gated on that repo's data existing, not something to build ahead of it.

## 0. What this is

007 is a private harness that drives `claude`/`codex` over Own.NET and OwnAudit
via their CLIs, in a throwaway `git worktree`, gated by `.007/gate.toml`. Its own
ADR (`007/docs/security-layers.md`) is honest that the worktree is not a
sandbox and gate steps are attacker-controlled code execution if the target
repo isn't fully trusted. 007's Zero Trust roadmap closes that gap in phases —
Sandboy isolation, a capability manifest, structured audit events. The last
phase in that roadmap is: **something has to look at the resulting evidence and
decide what's noise vs. a real incident.** That's this repo's job, not 007's —
007 orchestrates and enforces; it isn't built to triage its own findings, same
reason OwnAudit doesn't run its own detectors (see
[`docs/proposals/P-024-security-audit-profile.md`](https://github.com/PhysShell/Own.NET/blob/main/docs/proposals/P-024-security-audit-profile.md)
in Own.NET: "оркестратор, не анализатор" applies here verbatim).

## 1. Reuse, don't build a new pipeline

OwnAudit already has the exact shape this needs, built for a different evidence
source:

- **The confirmed / static-only / runtime-only triage** in
  [`runtime-contract.md`](runtime-contract.md) — a static finding plus
  independent corroborating evidence (heap retention) becomes `confirmed`; a
  finding with no corroboration is a suspect false positive; corroboration with
  no matching finding is the analyzer's **blind spot**. The same three buckets
  apply directly to policy events: a capability violation that the manifest
  intended to catch and did → `confirmed`; a violation rule that never fires →
  candidate for retirement; an agent action that *succeeded* but matched no rule
  at all → **policy gap** (the blind spot — a candidate for a new rule, exactly
  like "runtime-only" means "the static analyzer's blind spot" today).
- **The rule → verdict methodology** in
  [`audit-data-leverage.md`](audit-data-leverage.md) — findings are concentrated
  (top-N rules dominate volume), so characterizing a handful of rules
  characterizes most of the backlog. The same applies to gate/policy rules: a
  network-deny rule that fires on every run because a common tool phones home
  for a version check is noise to tune, not a real incident every time.

Nothing here is a new detection engine. It's the same normalize → aggregate →
score → report pipeline, fed a new evidence source.

## 2. What gets ingested

From a 007 run record (`runs/<target>/<run-id>/`): `meta.json` (run identity —
`run_id`, `agent_id`, `target_repo`, `base_commit`, `policy_id`), `gate/*.log` +
`gate/verdict.json` (per-step pass/fail), and — once Phase 1 lands — capability
manifest violations (attempted network egress under `network = "deny"`, a write
outside the declared scope, an unrecognized `[permissions]` field that failed
closed) and output-filter hits (a secret pattern caught before it reached
`agent.stdout`/`diff.patch`).

**Before trusting any of it, verify provenance.** 007's records are meant to be
hash-chained (`prev_record_hash`/`record_hash` over the gate manifest, each
step's sandbox policy, the task, the diff, and stdout — see
`007/docs/zero-trust-framework.md` §5). The ingest adapter's first move is
checking that chain, the same reflex `runtime.json`'s consumer already applies
to its own inputs: a broken chain (or a hash that doesn't match the artifact it
claims to describe) is itself the finding — `provenance-broken`, filed
alongside the buckets below, not silently trusted because the JSON parsed.

Concrete instances of the `policy-violation-confirmed` bucket worth naming, so
"triage" doesn't stay abstract: a step whose policy declares `tcp_connect = []`
shows a denied connect attempt anyway (the boundary caught something — log it,
it's not automatically an incident); a step writes outside its declared `fs_rw`
scope and gets denied; the diff touches `.007/policies/**` without the task
naming a policy change; the diff touches `.007/gate.toml` itself — that last one
is `policy-violation-allowed-then-flagged` even when the gate step technically
passed, because an agent editing its own leash is the one action this pipeline
should never wave through unread.

This is **not** source-code SARIF — there's no file/line to point at, the
"finding" is about a process's behavior during a run, not a static code
location. It needs its own thin record shape and its own adapter into the
existing aggregation, parallel to how `zap_to_sarif` / `dotnet_vuln_to_sarif`
adapt non-native tool output in the security profile (P-024 in Own.NET) — not a
new report pipeline, a new adapter feeding the one that exists.

```jsonc
// illustrative — the shape 007 would emit, the adapter's input
{
  "schema": "o7/audit-event/v1",
  "run_id": "…",
  "agent_id": "claude",
  "target_repo": "Own.NET",
  "policy_id": "own-net.cue#<hash>",
  "events": [
    {
      "kind": "policy-violation",
      "rule": "network.default",
      "action": "connect example.com:443",
      "step": "regression",
      "outcome": "denied"
    }
  ]
}
```

## 3. Triage buckets

| Bucket | Meaning | Action |
|---|---|---|
| `policy-violation-confirmed` | an action tripped a capability-manifest rule and was denied | evidence of the boundary working — log, don't page |
| `policy-violation-allowed-then-flagged` | an action matched a rule marked `requires_approval` and proceeded | the actual triage queue — did a human actually approve it, or did it slip through |
| `policy-gap` | an action succeeded, matched no rule at all | the manifest's blind spot — candidate for a new rule, same lens as "runtime-only" in `runtime-contract.md` |
| `suppressed-noise` | a rule fires on nearly every run for a benign reason (e.g. a toolchain's version-check phones home) | tune the rule, don't keep flagging it — same rule→verdict lens as `audit-data-leverage.md` |

## 4. Non-goals

- **Not enforcement.** OwnAudit never blocks or allows an agent action — that
  authority stays at 007 + Sandboy, at the process boundary, before the action
  happens. This repo only ever looks at what already happened.
- **Not disposition.** Per the Zero Trust framework this whole effort traces
  back to: agents can automate evidence collection, enrichment, and drafting an
  incident note; containment, rerun, and escalation decisions stay a human
  call. A `policy-violation-allowed-then-flagged` event becomes a note a person
  reads, not an automatic rerun/block.
- **Not a new detector engine.** Same charter as P-024 in Own.NET: no bespoke
  heuristics, no own severity model reinvented from scratch — reuse the
  cross-tool-agreement scorer and the coverage-map discipline (`NO-TOOL:
  skipped` beats a guess) that already exist for static and runtime findings.

## 5. Cross-repo division of responsibility (this repo's view)

| Concern | Owner |
|---|---|
| Declares/verifies the capability vocabulary (`owen.policy`, authored in CUE) | Own.NET — `docs/notes/agent-capability-layer.md` |
| Process/syscall isolation boundary | Own.NET — `sandboy/` |
| Enforces policy at runtime, emits the structured audit trail | 007 — `docs/zero-trust-framework.md` |
| Ingests the trail, triages, reports, keeps disposition human | **OwnAudit** — this doc |

## 6. Where this lands

Layout, if/when 007 Phase 1 lands and this gets built:

```text
audit/agent-runs/           # parallel to audit/security/ (Own.NET)
  adapters/                 # o7_run_to_finding.py
  profiles/                 # which run stores to poll, retention window
```

Consistent with the existing lift-out discipline (`PLAN.md`): the pipeline
logic belongs wherever the rest of `audit/aggregate` lives at build time, and
this repo carries the boundary + validated runs, same as everything else here.
