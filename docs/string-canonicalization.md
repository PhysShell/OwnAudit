# String canonicalization under .NET 4.7.2 — design note

The data-duplication axis (`docs/wpf-audit-coverage.md`), taken to its most valuable special
case: **duplicated `System.String`**. In a long-running WPF/DevExpress LOB app, bounded-vocabulary
strings — status codes, column names, enum-ish labels, dictionary values rehydrated per row/DTO —
get allocated thousands of times. Same bytes, different references, all retained. This note
captures the whole "CLR string surgery" branch so nothing is lost, and frames it in the project's
own terms: **analyzer first, targeted mutator second, never a heap rewrite.**

This is the same methodology as the rest of Own.NET — *measure → confirm → targeted fix → re-measure*
(the phase-2 ratchet + phase-5 runtime-confirm loop), just pointed at strings. The mutator half is
a fix-arm-style tiered intervention, kept strictly opt-in.

---

## Phase A — Analyzer (folds into Own.NET, build-free to consume)

Objective measurements before anyone touches a pointer. Two sources:

**heap (primary).** ClrMD / dotnet-gcdump heap walk after a scenario → enumerate every
`System.String`, group by content, and report per value:
- `count` — live instances,
- `total_bytes` — Σ object size,
- `wasted_bytes` — `(count − 1) × size` if canonicalized to one,
- `retention` — the dominators / GC-root paths keeping them alive,
- `long_lived_only` — filter to gen2 / pinned, ignore transients.

This is the phase-5 collector extended with a string lens — it emits the same kind of artifact
(`strings.json`, shape mirrors `runtime.json`'s `retained[]`) that the Python side correlates and
the dashboard renders. Top-N by `wasted_bytes` is the actionable output.

**C# (birth sites).** A Roslyn pass that flags *where* repeated long-lived strings are born —
`StringBuilder.ToString()`, `string.Concat`, DTO ctors/factories, parsers/deserialization,
setters/hydration code — so the report points at call sites, not just values.

The analyzer alone is the 80% win: it replaces intuition with **top-20 values by wasted bytes +
their birth sites + retention roots**, which is exactly the report you want before deciding whether
canonicalization is even worth it.

## Phase B — Mutator (separate, gated, net472-specific track)

Only for **approved hot sites**, **bounded-vocabulary** values, **new strings only**. Never the
existing heap. The menu, cheapest→heaviest:

1. **`AdaptiveStringCanonicalizer`** (the policy core, not a mechanism) — *not* `String.Intern`.
   Own dictionary with evictable / weak semantics where possible, a `count` threshold and an
   `estimated-saved-bytes` threshold, metrics built in. `String.Intern` is rejected as the
   default: its pool is process-lifetime and never collected, so it trades duplication for an
   unreclaimable leak.
2. **Build-time IL weaving** (Mono.Cecil / Fody) — insert `value = Canonicalizer.Canonicalize(value)`
   after the approved string-producing calls. Pros: no GC, no object-graph rewrite, trivially
   revertible, works on Framework. The pragmatic default for the mutator.
3. **CLR Profiling API** (`ICorProfilerCallback`) — the grown-up runtime path for net472, in two
   modes:
   - *observe*: `ObjectAllocated` for allocation stats, `ObjectReferences`/`RootReferences2` to
     build the retention graph (overlaps Phase A's heap source),
   - *scalpel*: `SetILFunctionBody` + `RequestReJIT` (ReJIT is available on 4.5+) to rewrite
     specific methods so new strings route through the canonicalizer.
   Most powerful, heaviest to operate.
4. **Harmony** (`Lib.Harmony`) prefix/postfix/transpiler on managed string factories — dirty but
   fast for a one-evening PoC of a single pipeline. Coverage is poor and it's easy to introduce
   behavioural schizophrenia; not for broad surgery.

## Explicitly rejected — whole-heap reference rewrite

The seductive version ("build the object graph, pick a canonical instance per value, mass-rebind
every reference, sync with the GC") is **out of scope, on purpose.** It breaks the world:
- `ReferenceEquals(a, b)` and any identity-keyed cache (`ConditionalWeakTable`, identity hash);
- `lock(someString)` (monitor uses object identity / sync block);
- `unsafe` code that mutates or pins strings on the assumption they're private;
- compatibility becomes sticky and miserable.

This is precisely why the runtime's own GC string-dedup design (dedup thread, old generations,
weak handles, CAS on reference swap, no stack refs) **never shipped** in dotnet/runtime — it works
in environments where strings don't expose identity the way .NET's do. For net472 this is GC/runtime
territory, not a library, and "truly patch the CLR without it later being agony in prod" is the
opening line of a bad on-call legend. We don't go there.

## Staged PoC plan

1. Small profiler/ClrMD report of duplicated strings (Phase A heap source).
2. Top-20 values by wasted bytes + their top call sites / retention roots (Phase A C# source).
3. Proof-of-concept `AdaptiveStringCanonicalizer` with metrics.
4. IL weaving (Cecil) **or** Harmony at 2–3 approved sites only.
5. Re-measure — wasted bytes before/after. Feedback loop, not a one-shot.

That simulates runtime string dedupe exactly where it pays, without becoming a garbage collector
for an afternoon.

## net472 specifics

- **Profiling API**: `ICorProfilerCallback2/3`; enable via `COR_ENABLE_PROFILING` + profiler GUID.
  Heavyweight, but the only first-class retention-graph source in-process.
- **ReJIT**: `RequestReJIT` / `SetILFunctionBody` are available since 4.5 — usable on 4.7.2.
- **Cecil/Fody**: build-time IL rewrite works on Framework assemblies; easiest to ship and revert.
- **ClrMD** (`Microsoft.Diagnostics.Runtime`): attach to a live process or open a dump, enumerate
  the heap, group strings — the analyzer's backbone.
- **`String.Intern`**: exists, but its pool is never collected → memory can't be reclaimed; use the
  adaptive canonicalizer instead.

## Where this is testable *here* (Avalonia oracle)

String duplication is pure CLR/heap, so the **entire Phase A analyzer is framework-agnostic and
testable on the Avalonia oracle** (or any .NET app we build in this container) — group strings,
report wasted bytes, find birth sites. The build-time Cecil weaving path is cross-platform too, so
even a slice of Phase B can be exercised here. The Profiling-API/ReJIT scalpel is the one piece that
stays a stand exercise. So this branch isn't STS-only — most of it validates on the oracle, same as
phases 3–5.
