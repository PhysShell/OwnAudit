# The Own.NET oracle — a deliberately-leaky Avalonia app

A **real target** for the audit pipeline: the cross-platform analog of STS that we *can* build and
run here, so phases 3–5 get exercised on real data instead of synthetic fixtures (see
[`docs/own-net-auditor.md`](../docs/own-net-auditor.md) and
[`docs/wpf-audit-coverage.md`](../docs/wpf-audit-coverage.md)).

This is **слой 1** of the oracle plan. It is *not* part of the auditor — it is a thing the auditor
runs against. The **слой 2** Roslyn graph-extractor (and the ClrMD heap collector) that read this app
are **Own.NET-canonical** and land there, not in OwnAudit — same repo boundary as the XAML analyzer
(`docs/xaml-analyzer-design.md`). Until then, the app stands on its own and *proves it leaks*
headlessly.

## Why Avalonia

Avalonia is the framework-agnostic-core analog of WPF: the leaks that matter for STS — event-lifetime
leaks, un-recycled list containers, duplicated strings — behave **identically** on the CLR heap, so
they validate the audit on real data. The WPF-only tail (Freezable, `x:Shared`, DevExpress) is STS-only
and deliberately absent here (`docs/wpf-audit-coverage.md`, "Avalonia mappability").

## The intentional smells

| Smell | Where | Rule it exercises |
|---|---|---|
| **Subscription leak** — `+=` to an app-scoped service, never `-=` | `ViewModels/WatchlistViewModel.cs` | OWN001 (event lifetime) + phase-5 heap confirm |
| **Duplicated strings** — `new string(...)` per row, identical content | `ViewModels/WatchlistViewModel.cs` | string-canonicalization (`docs/string-canonicalization.md`) |
| **Virtualization killed** — `ListBox` `ItemsPanel` swapped to a plain `StackPanel` | `Views/MainWindow.axaml` | XAML107 (`VirtualizationExplicitlyDisabled`) + heap confirm |

`ViewModels/FixedWatchlistViewModel.cs` is the corrected counterpart (detaches on `Dispose`) — the
control case that keeps the leak proof honest and gives the fix-arm a before/after target.

## Build & run

```bash
# .NET 8 SDK required (Avalonia 11 targets net8.0)
cd oracle/LeakyOracle
dotnet build -c Release

# headless leak proof — no display, CI-friendly. exit 0 == leaks as designed.
dotnet bin/Release/net8.0/LeakyOracle.dll --leak-scenario

# the actual GUI (needs a desktop session)
dotnet run -c Release
```

`tools/leak-scenario.sh` wraps the headless proof (sets DOTNET_ROOT, builds, runs).

### What the leak proof shows

```
screens opened+closed   : 50
leaky  still alive (GC) :  50  (expect 50 — rooted by MarketDataService.QuoteReceived)
fixed  still alive (GC) :   0  (expect 0 — detached on Dispose)
verdict                 : LEAK confirmed and isolated to the un-detached subscription
ORACLE OK: leaks as designed — a valid target for the heap/lifetime audit.
```

Both view-models go through the **same** WeakReference harness: the leaky one survives a full GC
(rooted by the service event), the fixed one is collected. Checking both proves the harness isn't
rigged — a correct app collects, the oracle does not. If it ever stops leaking, the proof fails loudly
(exit 1): the oracle is broken, not the auditor.
