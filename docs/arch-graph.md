# `graph.json` — the architecture symbol graph (Own.NET Auditor phase 3)

The architecture pass (`arch/`) is a **pure-Python rules engine over a dependency graph**. It
does no .NET work itself; it consumes a `graph.json` that a small Roslyn extractor emits **on
the Windows stand** (where the STS solution actually builds). This keeps the heavy symbol
resolution where the SDK lives and keeps the analysis build-free and CI-testable here — the
same split the SARIF exporter and baseline differ already use against `findings.json`.

```text
   Windows stand (has .NET SDK + Roslyn)          Linux / CI (stdlib only)
   ┌─────────────────────────────────┐            ┌──────────────────────────────┐
   │ Roslyn extractor                │  graph.json│ arch/graph.py  (Graph, SCC)  │
   │  MSBuildWorkspace → symbols     │ ─────────► │ arch/rules.py  (layer/cycle/ │
   │  emit nodes + dependency edges  │            │                 god-class)   │
   └─────────────────────────────────┘            │ arch/cli.py → arch-findings  │
                                                   └──────────────────────────────┘
```

`arch-findings.json` comes out in the **same shape as `sts_audit/findings.json`**, so it flows
through the existing SARIF export (`report.cli`), baseline diff/gate (`report.diff_cli`) and the
dashboard unchanged — tool `own-arch`, category `architecture` (→ SARIF `warning`).

## Schema (v1)

```jsonc
{
  "schema": "ownAudit/arch-graph/v1",
  "nodes": [
    {
      "id": "T:Sts.Broker.Orders.OrderService",   // stable unique id (use the symbol's DocId)
      "kind": "type",
      "name": "OrderService",                      // short type name
      "namespace": "Sts.Broker.Orders",
      "assembly": "Sts.Broker",
      "internal": true,                            // defined in the audited solution? (default true)
      "loc": { "file": "Broker/Orders/OrderService.cs", "line": 14 },
      "metrics": { "methods": 22, "fields": 9, "loc": 410 }
    }
    // ... external/framework types appear too, with "internal": false and (usually) no loc/metrics
  ],
  "edges": [
    { "from": "T:Sts.UI.Views.OrdersView", "to": "T:Sts.Data.SqlOrderRepo", "kind": "depends" }
  ]
}
```

**Nodes.** One per type symbol the extractor sees — both internal types and the external
(framework/third-party) types they reference. Only `internal: true` nodes are ever *flagged*;
external nodes exist so a layering rule can name a forbidden *target* (e.g. `System.Windows.*`).
A node with no `internal` key is treated as internal (ours).

- `id` — any stable unique string; the Roslyn `ISymbol.GetDocumentationCommentId()` ("DocId")
  is ideal because it's stable across builds.
- `namespace` / `assembly` — used to roll the type graph up for namespace- and assembly-level
  cycle detection.
- `loc` — where to anchor a finding. Optional for external nodes.
- `metrics` — optional; feeds the god-class composite. `deps_out` is **not** read from here —
  the engine computes fan-out from the edges so it can't be gamed by a stale metric.
- `is_abstract` — **optional**, forward-compatible. A `bool`: is this type abstract or an
  interface? When present, the coupling metrics (`arch/metrics.py`) light up **Abstractness A**
  and **Distance from the main sequence D = |A + I − 1|** per component automatically; when
  absent they stay `null` and nothing else changes. Cheap to add in the extractor
  (`symbol.IsAbstract || symbol.TypeKind == TypeKind.Interface`).

**Edges.** A directed `from → to` "type `from` depends on type `to`" (field/property type, base
type, method parameter/return, instantiation, attribute, generic arg…). `kind` is currently
always `"depends"`; reserved for future weighting. Self-edges and duplicate edges are
collapsed/ignored by the loader.

## What the engine asks of the graph

| Rule | Needs | Notes |
|---|---|---|
| `ARCH-CYCLE-{TYPE,NS,ASM}` | edges | Tarjan SCC (iterative — STS namespace graphs are deep); an SCC of size >1 is a cycle. NS/ASM by rolling the type graph up on `namespace`/`assembly`. |
| `ARCH-UI-SQL`, `ARCH-DOMAIN-WPF` | edges + `namespace`/`assembly`/`name` | forbidden direction; **source must be internal**, target may be external. Patterns are case-sensitive fnmatch globs (`arch/rules.json`). |
| `ARCH-GOD-CLASS` | `metrics` + edges | composite: crosses ≥ `min_signals` of {methods, fields, loc, deps_out} thresholds at once. |
| `ARCH-SDP`, `ARCH-UNSTABLE-HUB` | edges + `namespace`/`assembly` | Martin coupling metrics (Ca/Ce/Instability) per component; SDP flags a stable component depending on a less stable one, unstable-hub flags high-Ca-and-high-Ce. `is_abstract` adds A/D when present. |

## Roslyn extractor — sketch (stand-side, not in this repo)

A ~one-file `dotnet run` tool. Not committed here because it needs the .NET SDK and only runs
on the stand; this is the contract it must satisfy.

```csharp
// dotnet add package Microsoft.CodeAnalysis.Workspaces.MSBuild
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.MSBuild;

MSBuildLocator.RegisterDefaults();
using var ws = MSBuildWorkspace.Create();
var solution = await ws.OpenSolutionAsync(args[0]);

var nodes = new Dictionary<string, object>();
var edges = new HashSet<(string, string)>();

string Id(INamedTypeSymbol s) => s.GetDocumentationCommentId() ?? s.ToDisplayString();

void AddNode(INamedTypeSymbol s, bool isInternal)
{
    var id = Id(s);
    if (nodes.ContainsKey(id)) return;
    var loc = s.Locations.FirstOrDefault(l => l.IsInSource);
    nodes[id] = new {
        id, kind = "type", name = s.Name,
        @namespace = s.ContainingNamespace?.ToDisplayString() ?? "",
        assembly = s.ContainingAssembly?.Name ?? "",
        @internal = isInternal,
        loc = loc is null ? null : new {
            file = loc.SourceTree!.FilePath, line = loc.GetLineSpan().StartLinePosition.Line + 1 },
        // metrics: walk members for method/field counts + line span for loc
    };
}

foreach (var project in solution.Projects)
{
    var comp = await project.GetCompilationAsync();
    foreach (var type in comp!.GlobalNamespace.GetAllTypes())   // helper: recurse namespaces
    {
        if (!type.Locations.Any(l => l.IsInSource)) continue;    // internal = has source here
        AddNode(type, isInternal: true);
        foreach (var dep in TypeDependencies(type))              // fields, bases, params, ctors…
        {
            var depType = dep.OriginalDefinition;
            AddNode(depType, isInternal: depType.Locations.Any(l => l.IsInSource));
            if (!SymbolEqualityComparer.Default.Equals(type, depType))
                edges.Add((Id(type), Id(depType)));
        }
    }
}
// write { schema = "ownAudit/arch-graph/v1", nodes = nodes.Values, edges = edges.Select(...) }
```

`TypeDependencies` = the union of: base type + interfaces, field/property types, method
parameter/return types, instantiated types (from the syntax/semantic model), generic type
arguments, and attribute classes. Resolution accuracy is the extractor's job; the Python side
only trusts the resulting `(from, to)` edges.

## Running the pass

```bash
# on the stand, after the extractor writes sts_audit/graph.json:
python3 -m arch.cli --graph sts_audit/graph.json --rules arch/rules.json
#   → arch/out/arch-findings.json   (findings.json shape)
#   → arch/out/arch-report.md

# then fold the architecture findings into the gate like any other tool:
python3 -m report.diff_cli --current arch/out/arch-findings.json --baseline sts_audit/arch-baseline.json
```
