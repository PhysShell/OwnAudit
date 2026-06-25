# OwnAudit

A one-shot **audit orchestrator** for the STS legacy WPF desktop app. It does not
analyze code itself — it drives existing tools (Own.NET/OwnSharp, Roslyn analyzers,
FlaUI, ClrMD), collects their evidence, and produces one ranked leak/risk dossier.

> **Core stays thin.** OwnAudit is the control panel, not a new checker. It consumes
> Own.NET strictly through its CLI outputs (`own-check.ps1` → SARIF) and never
> references core source. `C:\Repos\Own.NET` is untouched by design.

See **[PLAN.md](PLAN.md)** for the full design, the seven decisions behind it, and
the phased build-out.

## Layout

```
src/OwnAudit.Cli        own-audit CLI (static | runtime | report | config)
src/OwnAudit.Core       Finding model + AuditConfig (the hard-wall contract)
src/OwnAudit.Static     Arm 1 — OwnSharp backbone + Roslyn analyzers -> ranked suspects
src/OwnAudit.Runtime    Arm 2 — FlaUI drive + ClrMD heap-diff (top suspects only)
src/OwnAudit.Reporting  Arm 3 — ranked markdown + SARIF dossier
config/ownaudit.json    paths to Own.NET + STS, analyzer set
spike/                  the first runnable tasks (derisk before building the pipeline)
scenarios/              Arm 2 UI scenarios (YAML)
```

## Today (scaffold)

The CLI verbs are wired as seams; build-out is phased. The live entry points are the
spikes:

```powershell
# Arm 1a — OwnSharp over STS (no build needed) -> artifacts/ownsharp-sts.sarif
spike\Invoke-OwnSharpOnSts.ps1

# Arm 1b — prove headless msbuild + analyzer SARIF on the legacy tree
spike\Invoke-BuildSpike.ps1
```

## Build

```powershell
dotnet build OwnAudit.slnx
```
