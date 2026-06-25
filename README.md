# OwnAudit

The **lift-out home** for Own.NET's audit pipeline. The audit itself is **canonical in
[`Own.NET/audit/`](https://github.com/PhysShell/Own.NET/tree/main/audit)** — an
orchestrator that runs ready-made analyzers over a legacy .NET 4.7.2 / WPF / DevExpress
app, normalizes everything to SARIF, scores by cross-tool agreement, and renders a
health report ranked by "where it hurts most." **Don't reimplement it here.**

This repo holds:
- the **separate-repo boundary** — Own.NET's `Plan.md §7` lift-out destination;
- **`Run-Audit.ps1`** — reproduce the STS health report through `audit/`;
- **validated `artifacts/`** — a real run over STS (380 findings);
- a thin **.NET skeleton** (`src/`) reserved for `audit/`'s C# on lift-out + the
  deferred ClrMD duplicate-detector.

## Run the audit over STS

```powershell
pwsh ./Run-Audit.ps1
# -> artifacts/health-report.md (+ .html, .json)
```

It drives the canonical pipeline — OwnSharp (build-free) → SARIF → `audit/aggregate`
normalize → score → report. Needs `dotnet` + `python` on PATH; uses a worktree of
Own.NET `main` (where `audit/` lives). `PYTHONUTF8=1` is set to dodge the cp1251
console crash on the Russian-locale Windows target.

## Where things live

| concern | home | status |
|---|---|---|
| static aggregation, taxonomy, scoring, reporters | `Own.NET/audit/aggregate` + `audit/static` | **canonical** |
| runtime LeakHarness / DuplicateDetector / storm profiler | `Own.NET/audit/runtime` | **canonical** |
| boundary + STS runner + artifacts + lift-out home | `OwnAudit/` (this repo) | active |

See [PLAN.md](PLAN.md).
