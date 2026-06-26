# WPF audit pack — coverage matrix (Own.NET Auditor §4)

What the auditor can detect for a WPF/DevExpress LOB app like STS, *by detection technique*, and
how honestly each maps onto an **Avalonia** oracle (the cross-platform stand-in we can build and
run here — see `docs/own-net-auditor.md`). The point of this doc is to draw the line between
"we've got this", "small rule away", and "whole surface we haven't built yet" — so nothing on
the wishlist quietly falls through.

## Detection techniques

| Tag | Technique | Where it runs |
|---|---|---|
| **C#** | Roslyn syntax/semantic analyzer over `.cs` | stand (graph/analyzer extractor) |
| **XAML** | analyzer over `.xaml`/`.axaml` (it's just XML — parseable even in Python) | stand or CI |
| **heap** | ClrMD / dotnet-gcdump heap walk after a scenario (phase 5 `runtime.json`) | stand |
| **trace** | runtime listeners: WPF binding-error trace, Dispatcher/notification counters | stand |

The governing principle is the phase-5 one, extended from leaks to perf/correctness:
**suspect statically, confirm at runtime.** A disabled-virtualization attribute is a *suspicion*
(XAML); 100k live containers for 100k rows is the *confirmation* (heap).

## Matrix

| Smell | Technique | Status | Avalonia |
|---|---|---|---|
| **Event leaks** | | | |
| `+=` without `-=` | C# + **heap** | ✅ core (own-check OWN001) + phase-5 confirm | ✅ 1:1 |
| static-event subscription from instance | C# + **heap** | ✅ + phase-5 confirm | ✅ 1:1 |
| `DependencyPropertyDescriptor.AddValueChanged` (roots in a static table forever) | C# | ✅ small rule | ❌ WPF-only (Avalonia: `GetObservable().Subscribe()` un-disposed — same category, diff API) |
| `CollectionChanged` / `PropertyChanged` subscription leak | C# + **heap** | ✅ | ✅ 1:1 |
| `CommandManager.RequerySuggested` static-event | C# | ✅ small rule | ❌ WPF-only |
| **Timers** | | | |
| `DispatcherTimer` / `Timers.Timer` / `Threading.Timer` no Stop/Dispose | C# + **heap** | ✅ small rule + confirm | ✅ 1:1 (`Avalonia.Threading.DispatcherTimer`) |
| **WPF binding** | | | |
| binding path doesn't exist | **trace** (reliable) / XAML (heuristic) | ⚠️ **no XAML analyzer, no trace collector** | ✅ Avalonia logs `LogArea.Binding` errors → trace maps |
| binding to an expensive property | XAML + heuristic | ⚠️ no XAML analyzer | ~ |
| binding errors via runtime log | **trace** | ⚠️ **no collector** (cheap + high value) | ✅ |
| `ElementName` / `RelativeSource` hell (complexity) | XAML | ⚠️ no XAML analyzer | ✅ (same XAML dialect) |
| **PropertyChanged hell** | | | |
| fat setter (one set → pile of `OnPropertyChanged`) | C# | ✅ Roslyn rule | ✅ 1:1 |
| cascading notifications | C# (call graph) + **trace** | ⚠️ partial; storms need trace | ✅ |
| duplicate / repeated notifications | **trace** | ⚠️ no collector | ✅ |
| UI-thread notification storms | **trace** (Dispatcher counters) | ⚠️ no collector | ✅ |
| **Virtualization** | | | |
| `IsVirtualizing=False` / `VirtualizationMode=Standard` (no recycling) | XAML + **heap** | ⚠️ XAML gap; **heap confirm falls out of phase 5** | ✅ (`VirtualizingStackPanel`/`ItemsRepeater`) |
| non-virtualizing `ItemsPanel` (StackPanel swap) | XAML + **heap** | ⚠️ XAML gap; heap confirm ✅ | ✅ |
| nested `ScrollViewer` / `CanContentScroll=False` kills virtualization | XAML | ⚠️ XAML gap | ✅ |
| heavy `DataTemplate` (element/nesting count) | XAML | ⚠️ XAML gap | ✅ |
| containers not recycled (live count ≫ visible rows) | **heap** | ✅ phase-5 native | ✅ 1:1 |
| DevExpress `GridControl` virtualization config | XAML (vendor) | ❌ vendor-only | ❌ no DevExpress |
| **Freezable** | | | |
| `Brush`/`Geometry`/`ImageSource` not `Freeze()`d | C#/XAML + **heap** | ⚠️ small rule | ❌ **Freezable is a WPF-only concept** |
| repeated immutable resources instead of static/shared | XAML + **heap** (dup count) | ⚠️ | ~ (heap-dup maps; Freeze doesn't) |
| **Data duplication** | | | |
| immutable reference data multiplied across VM/DTO | **heap** (N copies of a should-be-singleton) | ✅ phase-5 native | ✅ 1:1 |
| large collections copied needlessly | **heap** + C# (`.ToList()` in hot paths) | ⚠️ partial | ✅ |
| **duplicated strings** (the dominant case) | **heap** + C# birth-sites | → see [`string-canonicalization.md`](string-canonicalization.md) | ✅ 1:1 (pure CLR) |

## The two surfaces we haven't built (the honest gaps)

1. **XAML analyzer.** A large slice of the wishlist lives in `.xaml`, not `.cs`: binding paths,
   `ElementName`/`RelativeSource` complexity, **virtualization-disabled patterns**, nested
   `ScrollViewer`, heavy `DataTemplate`, Freezable-in-resources. We have a Roslyn (C#) extractor
   but nothing reads XAML. Biggest gap — and technically cheap: XAML is XML, rules are tree
   patterns. Avalonia `.axaml` is the same dialect, so it maps.
2. **Runtime-trace collector.** Beyond the heap snapshot there's a second runtime signal class —
   the WPF binding-error trace (`System.Windows.Data Error: 40 …`) and UI-thread notification
   counters. The heap collector doesn't see these; a small ETW/trace listener (or, on Avalonia,
   a `Logger` sink) would. Cheap, high value for binding correctness + storms.

One concept — **Freezable** — is WPF-only and won't exercise on the Avalonia oracle at all; that
tail is validated only on STS.

## Avalonia mappability — summary

The oracle honestly exercises **~70–80%** of the surface: all event leaks, timers, fat-setter,
virtualization (heap-confirmed), data duplication, string duplication, heavy templates (via the
XAML analyzer), binding errors (Avalonia logs them). It can **not** exercise: Freezable,
DevExpress controls, `CommandManager.RequerySuggested`, `DependencyPropertyDescriptor.AddValueChanged`.
Those are the STS-only tail.

Crucially, the framework-agnostic core — Roslyn graph, CLR heap — behaves identically, so phases
3–5 are validated on *real* data the moment we run them against a leaking Avalonia app.
