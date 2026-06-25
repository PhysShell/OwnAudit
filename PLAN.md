# OwnAudit — Plan

A **one-shot audit** of the STS legacy WPF desktop app (`C:\Repos\STS_new`,
`Broker.sln`). OwnAudit is an **orchestrator, not a checker**: it drives existing
tools, collects their evidence, and produces one ranked leak/risk dossier — then
runtime-proves the top suspects. It lives in its own repo and consumes Own.NET only
through that project's CLI outputs, so the Own.NET core gains **zero audit
dependencies**.

---

## The seven decisions

These came out of a design interview; they are the spine of everything below.

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Deliverable** | One-shot STS audit. Minimum orchestrator, one real evidence-backed report. Layered so it *can* generalize later — but no product surface (rule-pack DSL, multi-profile CLI, Avalonia/Maui) now. |
| 2 | **Proof bar** | Static-first, then prove the top suspects. Arm 1 (static aggregation) → ranked suspects → Arm 2 runtime-proves only the top N. |
| 3 | **Boundary** | Separate sibling repo (`C:\Repos\OwnAudit`). Consumes Own.NET only via its built CLI (`own-check.ps1` → SARIF). Core stays byte-for-byte unchanged — the wall is physical, not a convention. |
| 4 | **Build viability** | Spike the build *before* committing the analyzer pipeline. The legacy tree may not compile headless; don't assume. |
| 5 | **OwnSharp role** | Backbone **and** dogfood target. OwnSharp leads the leak hunt (it owns subscription-leak detection nothing else has, and needs no build); the audit is its biggest test; its false-positives/misses feed back as Own.NET issues. |
| 6 | **Runtime arm** | Minimal-touch: FlaUI drives the built exe, ClrMD heap-diffs. Add SemantixTrace's `AutoAutomationId` only if FlaUI can't navigate. Breadcrumbs + the Rust oracle are deferred. |
| 7 | **Stack** | .NET console (`own-audit` CLI), `net8.0-windows`. Arm 2's FlaUI/ClrMD are .NET-native; Arm 1 is process-glue + SARIF parsing. |

---

## Context (facts from disk)

- **Own.NET / OwnLang** (`C:\Repos\Own.NET`) — a C# lifetime/resource-leak analyzer.
  Pipeline: `OwnSharp.Extractor` (Roslyn, C#) emits OwnIR facts JSON →
  `python -m ownlang ownir` produces verdicts (`OWN001/002/003` dispose/use-after,
  `POOL002/005` pooled buffers, `WPF002/004` timer/Rx, `OWN014` subscription leak).
  The `scripts/own-check.ps1` wrapper chains both stages and can emit **SARIF**
  (`-Format sarif`, written to stdout) — this is OwnAudit's single integration seam.
  OwnSharp builds its *own* compilation from source, so it does **not** require the
  target to build; unresolved references degrade to `OWN050` honest-skips.
- **STS** (`C:\Repos\STS_new`) — the audit target. `Broker.sln`, **.NET Framework
  net472**, **classic non-SDK csproj**, **packages.config**, **Platform x86**, WPF
  (MahApps/ControlzEx/Xaml.Behaviors/SharpVectors). Pulls **private-feed** packages
  (`Cat.*`, `Sector.*`) — clean restore may need the internal feed (reachable via the
  `~/.claude` AZDO helper). `Broker` is a *library*; the WinExe startup project lives
  elsewhere in the solution (identify it for Arm 2).
- **SemantixTrace** (`C:\Repos\SemantixTrace`) — not empty: a Rust trace engine
  (`trace-cli`: ingest/normalize/align/analyze/**oracle**/report) plus .NET adapters
  (`Trace.Wpf`: `FileJsonlTraceContext`, **`AutoAutomationId`**, `TracedRelayCommand`).
  Mostly **deferred** here — only `AutoAutomationId` is a candidate pull-in for Arm 2.

---

## Architecture & boundary

```
C:\Repos\Own.NET            ← UNTOUCHED. ships CLI artifacts only:
  scripts/own-check.ps1  ──►  SARIF   (OwnSharp.Extractor + python -m ownlang)
        │  (consumed as outputs — no source reference)
        ▼
C:\Repos\OwnAudit          ← THIS repo. net8.0-windows `own-audit` console
  OwnAudit.Core       : Finding model + AuditConfig  (the hard-wall contract)
  OwnAudit.Static     : Arm 1 — OwnSharp + Roslyn analyzers → normalize → rank
  OwnAudit.Runtime    : Arm 2 — FlaUI drive + ClrMD heap-diff (top-N)
  OwnAudit.Reporting  : Arm 3 — ranked dossier (markdown + SARIF)
        ▲
C:\Repos\SemantixTrace     ← DEFERRED. AutoAutomationId only if FlaUI can't navigate;
                             breadcrumbs + Rust oracle = a later phase
```

The dogfood feedback (OwnSharp FP/FN found on STS) flows back to Own.NET as **issues**,
never as code coupling.

---

## Repo layout

```
OwnAudit.slnx
src/OwnAudit.Cli/         own-audit dispatcher (static | runtime | report | config)
src/OwnAudit.Core/        Finding.cs, AuditConfig.cs
src/OwnAudit.Static/      OwnSharpRunner.cs (live seam), StaticArm.cs
src/OwnAudit.Runtime/     RuntimeArm.cs (Scenario, RetentionProof)
src/OwnAudit.Reporting/   DossierWriter.cs
config/ownaudit.json      paths to Own.NET + STS, analyzer set
spike/                    Invoke-OwnSharpOnSts.ps1, Invoke-BuildSpike.ps1
scenarios/                Arm 2 UI scenarios (YAML)
artifacts/                generated SARIF / dossiers / binlogs (gitignored)
```

---

## Arm 1 — static aggregation (build first)

**OwnSharp (backbone).** Shell out to `own-check.ps1 -Format sarif -Severity warning
-- <target>` and capture SARIF (`OwnSharpRunner`). Runs over *all* of STS with no
build. Unique value: `OWN014` subscription leaks — the #1 WPF retainer — which no
third-party analyzer detects.

**Roslyn analyzers (breadth)** — only on projects that compile, gated on the build
spike. Because STS is packages.config/non-SDK, conditional `<PackageReference>`
(variants A/B) is unreliable; use **variant C** — a root `Directory.Build.targets`
injecting `<Analyzer Include="…dll"/>` items from a restored cache, plus `ErrorLog`
(SARIF) and `ReportAnalyzer`. Non-SDK csproj import `Directory.Build.targets` too, so
one file covers the tree. Run inside a **git worktree** of STS so the dev copy is
untouched. Analyzer set (leak-relevant first, then breadth):
`IDisposableAnalyzers`, `Microsoft.CodeAnalysis.NetAnalyzers` (scope to leak rules —
CA2000/1001/2213 — to avoid the firehose), then `WpfAnalyzers`,
`PropertyChangedAnalyzers`, `Meziantou.Analyzer`, `Roslynator.Analyzers`, `AsyncFixer`.

**Normalize + rank.** Reduce both SARIF streams to `Finding`s, merge co-located
findings (raising `Corroboration`), and rank:

```
rank = leakClassWeight(Subscription/Timer/Dispose/Pool > Quality)
     × corroboration(distinct tools agreeing)
     × blast(type is a Window/ViewModel, instance-heavy)
```

The top N flow to Arm 2.

---

## Arm 2 — runtime proof (top suspects only)

Minimal-touch. **FlaUI** launches the STS WinExe (x86), runs an open→close scenario
×N, forces GC. **ClrMD** (x64 runner reads the x86 dump) counts retained instances of
the suspect Window/ViewModel types and `gcroot`s the survivors. Add SemantixTrace's
`AutoAutomationId` (global attached-property/style — one small change) *only* if FlaUI
can't otherwise find controls. Scenarios are YAML (`scenarios/*.yaml`), AI-drafted,
with **exact** deterministic asserts (retained counts / max growth) — never AI-judged.

**North-star artifact** (static suspect + runtime proof + root):

```
Scenario: OpenCloseDeclarationWindow ×10
After close:  DeclarationWindow +10 retained, DeclarationViewModel +10
Static:       OWN014 — DeclarationViewModel subscribes AppEventBus.Changed, no matching -=
Trace:        WindowClosed + ForcedGC emitted; gcroot still pins the VM via AppEventBus
```

---

## Arm 3 — reporting

`DossierWriter` renders the ranked findings (and Arm-2 retention proofs) into one
markdown dossier; a SARIF summary follows so findings can re-enter GitHub code
scanning / the IDE. Each top suspect gets a dossier entry: static evidence, runtime
delta, root path, suggested fix.

---

## The OwnSharp dogfood loop

Running OwnSharp on 600k lines of real legacy WPF is its biggest stress test (the same
FP/FN class being worked on `claude/pool-view-reassign-fp`). For each OwnSharp finding:
corroborate against analyzers / runtime truth; a confirmed false-positive or miss
becomes an **Own.NET issue** (with the STS snippet, reduced to a fixture). The audit is
two-for-one: STS findings **and** an OwnSharp hardening loop.

---

## Task order

0. **Scaffold** the OwnAudit repo. *(done — this commit)*
1. **Derisk + first signal (parallel):**
   - 1a `spike/Invoke-BuildSpike.ps1` — prove headless `msbuild` + analyzer SARIF on one
     leaf project. GREEN → analyzers scale to the sln; RED → OwnSharp-only on the
     non-building subset.
   - 1b `spike/Invoke-OwnSharpOnSts.ps1` — OwnSharp over STS now (no build). First
     findings + first dogfood list.
2. **Arm 1 build-out** — SARIF normalizer, analyzer injection across buildable projects,
   ranker → `own-audit static` → ranked dossier.
3. **Triage + dogfood** — review OwnSharp vs analyzer corroboration; file Own.NET FP/FN issues.
4. **Arm 2 spike** — FlaUI launch + one open-close on the #1 suspect window; ClrMD retained delta.
5. **Arm 2 build-out** — YAML scenario runner over the top N; fold heap proof into the dossier.
6. **Report v1** — the forensic artifact.

---

## Config

`config/ownaudit.json` (see `OwnAudit.Core.AuditConfig`): `ownNetRoot`,
`ownCheckScript`, `targetSolution`, `targetRoot`, `analyzers`, `artifactsDir`. It only
*names* the Own.NET checkout — it never references core code.

---

## Risks tracked

- **Private-feed restore** (`Cat.*`/`Sector.*`) — may block a clean build; internal
  source/feed reachable via the `~/.claude` AZDO helper.
- **Headless build** of a net472/x86/non-SDK WPF tree — the spike exists precisely to
  derisk this; analyzers are blocked if it fails (OwnSharp is not).
- **Missing AutomationIds** in legacy WPF — FlaUI tree heuristics first, then
  `AutoAutomationId`.
- **x86 bitness** — FlaUI drives out-of-process (independent); ClrMD reads the x86 dump
  from the x64 runner.
- **OwnSharp's first 600k-line run** — expect noise; that is the point, but budget triage.
- **NetAnalyzers SARIF firehose** — scope to leak rules first.

---

## Non-goals / deferred

- No rule-pack DSL, multi-profile CLI, or generalization to other repos yet (decision 1).
- SemantixTrace breadcrumb instrumentation of STS + the Rust trace-oracle (decision 6) —
  only `AutoAutomationId` is a candidate, and only if FlaUI needs it.
- OwnAudit is never a checker. If logic wants to live in the core, it is an Own.NET
  change reviewed on its own merits — not something Audit reaches in and adds.
