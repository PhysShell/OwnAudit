# `runtime.json` — the heap-retention artifact (Own.NET Auditor phase 5)

Runtime correlation (`runtime/`) is a **pure-Python pass** that diffs static leak findings
against observed heap retention. It does no profiling itself; it consumes a `runtime.json` that a
small heap-dump collector emits **on the Windows stand** after exercising a scenario (open/close
a window N times, run an import, …). Same split as `graph.json`: the .NET/CLR work stays where
the app runs; the correlation is build-free and CI-testable here.

```text
   Windows stand (app + CLR)                       Linux / CI (stdlib only)
   ┌──────────────────────────────────┐            ┌──────────────────────────────┐
   │ run scenario N× (open/close win)  │            │ runtime/correlate.py         │
   │ dotnet-gcdump / ClrMD heap walk   │ runtime.json│   static findings × dump     │
   │ count live instances + GC roots   │ ─────────► │ runtime/cli.py → confirmed / │
   └──────────────────────────────────┘            │   static-only / runtime-only │
                                                    └──────────────────────────────┘
```

The confirmed leaks come out in the **same shape as `findings.json`** (tool `own-runtime`,
category `runtime-confirmed-leak` → SARIF `error`), so they flow through SARIF/dashboard
unchanged, carrying a `confidence` and the static rule they corroborate.

## Schema (v1)

```jsonc
{
  "schema": "ownAudit/runtime/v1",
  "scenario": "open+close DocumentsWindow",   // human label for the report
  "iterations": 10,                            // how many times the scenario ran (optional)
  "retained": [
    {
      "type": "Sts.Broker.Documents.DocumentsViewModel",  // matched against a finding's `resource`
      "count": 132,            // live instances of this type still on the heap after the scenario
      "expected": 1,           // how many *should* survive (optional; default 1). 0 for transient
      "bytes": 88080384,       // retained bytes for these instances (optional; enriches the report)
      "roots": [               // GC roots keeping them alive (optional but high-value)
        { "kind": "static-event",
          "holder": "Sts.Broker.Documents.DocumentStore",  // the type owning the delegate
          "member": "Changed",                             // the event/field name
          "via": "delegate" }
        // other kinds: "static-field", "gc-handle", "thread-local", "timer", ...
      ]
    }
  ]
}
```

**`retained`.** One entry per type that still has live instances after the scenario. The
correlation keys on `type` ↔ the static finding's `resource`. `count - expected` is the
*excess* retention: `>= min_count` (config) confirms the static finding, `>= high_count` (or
any excess held by a `static-event` root) makes it **high** confidence. A `static-event` root is
the smoking gun for the classic WPF/event leak — it names exactly which static delegate is
pinning the instances.

## What the correlation produces

| Bucket | Meaning | Value |
|---|---|---|
| **confirmed** | a static leak finding AND runtime retention agree | highest-signal, low-FP — gate on these |
| **static-only** | a static leak finding with no retention | suspect false positive, or the scenario didn't exercise that path |
| **runtime-only** | retention with no static finding | the analyzer's **blind spot** — candidate for a new rule |

This is the FP-rate / blind-spot triage of `docs/audit-data-leverage.md`, made concrete: the
runtime is ground truth for "is this leak real".

## Stand-side collector — sketch (not in this repo)

Needs the CLR + the running app, so it lives on the stand. Contract it must satisfy:

```csharp
// dotnet tool install -g dotnet-gcdump   (or reference Microsoft.Diagnostics.Runtime / ClrMD)
// 1. launch STS, run the scenario N times (UI automation or a scripted harness),
//    forcing a full GC + a settle delay between iterations so transients collect.
// 2. capture a gcdump / attach ClrMD to the live process:
using Microsoft.Diagnostics.Runtime;
using var dt = DataTarget.AttachToProcess(pid, suspend: true);
var heap = dt.ClrVersions[0].CreateRuntime().Heap;

var live = heap.EnumerateObjects()
    .Where(o => o.Type is not null && IsAuditedType(o.Type.Name))
    .GroupBy(o => o.Type!.Name);

// 3. for each suspicious type, walk GC roots to find what pins it:
foreach (var root in heap.EnumerateRoots())
    // classify root.Kind: a static field holding a MulticastDelegate whose invocation list
    // contains the instance  -> { kind: "static-event", holder, member }.

// 4. emit runtime.json { schema, scenario, iterations, retained: [...] }
```

`expected` comes from the scenario design (a singleton view-model that should survive = 1; a
per-window VM after the window is closed = 0). Root classification accuracy is the collector's
job; the Python side only trusts the resulting `count`/`roots`.

## Running the pass

```bash
# on the stand, after collecting runtime.json:
python3 -m runtime.cli --findings sts_audit/findings.json --runtime sts_audit/runtime.json \
    [--gate-level high]
#   -> runtime/out/runtime-findings.json   (confirmed leaks, findings.json shape)
#   -> runtime/out/runtime-report.md       (confirmed / static-only / runtime-only)
```

Example confirmed line:

```text
MEM-WPF: 132 retained DocumentsViewModel (expected 1) held by static DocumentStore.Changed;
~84 MB retained [confirms static OWN001] — confidence: high
```
