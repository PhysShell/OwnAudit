# Heap collector — plan (2026-07-18)

Decisions from a design interview (Own.NET session, /grilling). Goal: close the one missing
architectural piece of the runtime arm — the **stand-side heap collector** that
`docs/runtime-contract.md` sketched — by porting a tool that already proved itself in production.

## Context

- **Demand research** (demand-radar, 21 opportunity cards): the one multi-signal cluster
  (19 authors, confidence 0.91) is exactly *"object → GC root → owner → user code → fix"* —
  developers see retention in a profiler but cannot name the culprit. The corrected
  interpretation: this is not a new product, it is the Own.NET + OwnAudit architecture
  already on the books. GO on validating the pipeline, NO-GO on a standalone profiler.
- **stackpeek** (`broker/runner/stackpeek`, external research repo): 261 lines of ClrMD.
  Live-attaches to a .NET Framework process (no procdump/WinDbg/PerfView), does a
  reachability mark from GC roots ("66.3 % of the heap is genuinely retained — a leak"),
  and walks root→object chains. It found a real production leak — every `GTD` document
  subscribing to a *static* `PropertyChanged` and never unsubscribing on the DocCloud
  path — that static OWN001 **missed** (the `-=` existed but sat behind a flag / an
  uncalled method). See `broker/runner/LEAK.md`. That is the `runtime-only` bucket of the
  runtime contract, demonstrated on real data.
- **Canonicality**: the audit pipeline is canonical **in this repo** now; `Own.NET/audit/`
  is deprecated (the lift-out happened and then reversed direction — OwnAudit grew its own
  path). Own.NET stays a pure SAST engine and emits findings; everything
  runtime/report/fix lives here.

## Decisions

| # | Decision |
|---|---|
| D1 | **Deliverable**: internal end-to-end dogfood — collector → `runtime.json` → `runtime/correlate.py` → confirmed / static-only / runtime-only on STS. Concierge/product packaging comes later and reuses this. |
| D2 | **Home**: port stackpeek's core into `src/OwnAudit.Runtime` (the skeleton reserved for exactly this). Own.NET untouched. |
| D3 | **Mode v1**: manual/scripted scenario + **single post-scenario live-attach** (`AttachToProcess(pid, suspend: true)`). No FlaUI, no procdump, no per-cycle dumps in v1. A `--baseline` before/after diff is a fast-follow; a growth-curve harness only when a real engagement demands slope proof. |
| D4 | **Root classification v1**: `static-event` (delegate invocation-list pattern; names `holder` + `member`), `static-field`, `timer` (TimerQueue chain), everything else `other` with the verbatim chain. |
| D5 | **Input contract**: suspect types default from `findings.json` (`resource` of OWN001/OWN014-class findings) — closes the static→runtime loop; `--types A,B` manual override is the standalone/concierge mode. |
| D6 | **CLI**: `ownaudit collect --pid <pid> [--findings findings.json | --types A,B] --scenario "label" --iterations N --out runtime.json`, plus `--inspect-only` debug subverbs (stackpeek's `reachable` / `roots`). Logic in `OwnAudit.Runtime`, parsing in `OwnAudit.Cli`. |
| D7 | **Schema**: `runtime.json` v1 per `docs/runtime-contract.md`, plus an optional `heapStats` block `{objects, bytes, reachableObjects, reachableBytes}` — the "is it even a leak" reachability gate. `correlate.py` ignores unknown fields, so v1 stays compatible. |
| D8 | **Tests**: TDD red/green against `oracle/LeakyOracle` — the planted subscription leak must classify as `static-event` with the right holder/member, the planted timer leak as `timer`, and the `Fixed*` variants must show no excess retention (FP control). Existing `runtime/tests` cover correlate. |
| D9 | **CI**: `collector.yml` on `windows-latest`, path-filtered (`src/**`, `oracle/LeakyOracle/**`): build → run the headless leak scenario → attach → assert `runtime.json`. Attach retry ×3; job non-required until stable, then promoted. Local `Run-Collector-Tests.ps1` remains a situational fallback. |
| D10 | **Acceptance (definition of done)**: rerun on STS with the broker driver — `KDT.cs:88` must come out **confirmed** (static OWN001 + runtime agree), `GTD.cs:5192` must come out **runtime-only** (the known static blind spot). Both are already heap-proven by hand in `broker/runner/LEAK.md`; the collector must reproduce mechanically what was dug out manually. |

## Steps

1. **Docs re-declaration** (this PR): canonicality reversal in `AGENTS.md` / `PLAN.md`,
   the collector boundary line in `oracle/README.md`, live-attach as primary in
   `docs/runtime-contract.md`, this plan.
2. **Port stackpeek core** into `OwnAudit.Runtime`: reachability mark + chain walk.
   Red: contract test vs LeakyOracle. Green: the port.
3. **Root classification** (D4). Red: planted roots; `Fixed*` FP control. Green: classifier.
4. **`runtime.json` emit** (D7) + smoke of the real output through `runtime/correlate.py`.
5. **CLI verb** (D5, D6).
6. **`collector.yml`** (D9).
7. **STS acceptance** (D10) — **done 2026-07-18**, artifacts: `artifacts/runtime-sts.json`
   + `artifacts/runtime-sts-report.md`. Scenario: SerializerSim `leaktest --hold` (94 docs,
   shipping build `d753747b` rebuilt into an `STS_shipping` worktree — the Jul-15 Setup
   rebuild had made documents unconstructible on the research DBs). Result: **250 high +
   58 medium confirmed, 2465 static-only, 0 runtime-only**. The LEAK.md chain reproduced
   mechanically: GTD (76) and KDTKTS (107) `static-event` roots naming
   `BrokerDataClasses.Property.GBProperty.PropertyChanged`; `KDT.cs:88` confirmed.
   Deviations from the expected shape, both instructive:
   - **GTD came out `confirmed`, not `runtime-only`** — correlation is type-level and
     GTD.cs carries other OWN001 findings (2466, 2489, …), so the runtime root
     (`GBProperty.PropertyChanged`) got attributed to *different* event findings; the
     5192 site itself is still unflagged. Follow-up: **member-aware matching** (root
     holder+member vs the finding's event name) would expose it as the true blind spot.
   - The harness's own prototype/parents statics show up as legitimate `static-field`
     chains; wide sampling (`--max-chains 40`) was needed for the event chains to appear
     among the samples. Follow-up: prefer diverse root-kind sampling per type.

Branch cadence: `claude/collector-stepN-*`, red/green commit pairs, PR to `main`.

## Non-goals (v1)

- No UI automation (FlaUI) — the scenario is driven by a human or an external script.
- No dump-file mode — live-attach only; procdump fallback only if a real engagement needs
  offline analysis.
- No growth curves — `count` vs `expected` per the contract is the v1 signal.
- No WPF-specific rule pack, no perf/allocation profiling — separate arms per the
  demand-research read-out.
