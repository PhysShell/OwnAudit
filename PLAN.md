# OwnAudit — Plan

OwnAudit is the **lift-out home** for Own.NET's audit pipeline. The pipeline is
**canonical in `Own.NET/audit/`**; this repo is its eventual standalone destination
(Own.NET `Plan.md §7`), and today it carries the separate-repo boundary, the STS
runner, and the validated artifacts.

## How we got here

A design interview produced seven decisions for a one-shot STS audit (one-shot ·
static-first then prove top suspects · separate repo · spike the build · OwnSharp
backbone + dogfood · minimal-touch FlaUI+ClrMD runtime · .NET console). While
scaffolding, we found Own.NET already contains `audit/` — an independent, **more
complete** implementation of the same architecture (and validated against real data).
Rather than maintain two, we **converged on `audit/`** and repurposed this repo as its
lift-out home. The redundant C# static/reporting stubs were retired.

## What lives where

- **Canonical — `Own.NET/audit/`:**
  - `aggregate/` normalize → score → report (markdown / json / merged-SARIF / HTML),
    with the OWN001 `[resource:]` split, OWN014 region-escape, the OWN050 coverage
    ledger, DevExpress baseline-suppress, cross-tool agreement, and the pain heatmap.
  - `static/` build-free runners (own-check, CodeQL `--build-mode=none`), variant-C
    analyzer injection, the rule→category taxonomy.
  - `runtime/` C# LeakHarness (FlaUI + procdump + ClrMD), DuplicateDetector,
    PropertyChanged-storm profiler, scenarios.
- **This repo — `OwnAudit/`:**
  - `Run-Audit.ps1` — reproduce the STS health report through `audit/`.
  - `artifacts/` — a validated run over STS.
  - `config/ownaudit.json` — Own.NET + STS paths.
  - `src/` — a thin .NET skeleton (Core + Runtime + Cli) reserved for `audit/`'s C#
    on lift-out and the deferred ClrMD duplicate-detector. **Not** a parallel impl.
  - `spike/` — the OwnSharp-on-STS + analyzer build-spike scripts (reference).

## Validated result (STS, this session)

OwnSharp (build-free) over `STS_new/SectorTS` → **380 findings in 49s** (0 errors),
fed through `audit/aggregate`:

- categorized with **zero misses**: 333 subscription/region-escape (cat 2), 47
  IDisposable (cat 1); **233 OWN050 routed to the coverage ledger**, not faked clean.
- heatmap: **`BrokerDataClasses` is the subscription-leak epicenter** (pain 284), then
  its StatementDT / Transit / KTS / DTS namespaces; `MainWindow.xaml.cs` alone ~10.
- **0 high-confidence — correctly, because only one tool ran.** Adding CodeQL
  (`--build-mode=none`, build-free) promotes agreed sites; that's the next lever.
- spot-checked **3/3 true positives**: `Mail.cs` SmtpClient with `//client.Dispose()`
  commented out; `KTSGoods2` static-singleton OWN014; `ShareWindow` undisposed `Timer`.

Artifacts: `artifacts/health-report.{md,html,json}`, `findings.json`, `ownsharp*.sarif`.

## Notes fed back to audit/

- **cp1251 crash:** `report.py` `print()` dies on `≥`/`·` on a cp1251 console (the STS
  target env). Fix: `sys.stdout.reconfigure(encoding="utf-8")`, or `PYTHONUTF8=1`
  (Run-Audit.ps1 sets the latter).
- **CodeQL build-free** is the corroboration unblock — no MSBuild / nuget / private feed.
- `owncheck.py` is correct (bash `own-check.sh`); the PowerShell `own-check.ps1` needs
  `-Paths`, not a `--` separator (a binder bug), if it is ever wired in.

## Lift-out (when audit/ should leave core)

Per Own.NET `Plan.md §7`: vendor `scripts/oracle_compare.parse_sarif`, move `audit/`
into this repo (its C# harness lands in `src/`), wire CI here. Deferred until "out of
core" is actually wanted; until then `audit/` stays in Own.NET with its decoupling
discipline (it imports nothing from `ownlang`).
