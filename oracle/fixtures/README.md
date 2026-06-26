# Oracle arch fixtures — the `graph.json` contract + a golden arch run

These fixtures let the architecture pass (`arch/`) be exercised on **real, oracle-shaped data**
right now — before the слой-2 Roslyn extractor exists — and pin the exact `graph.json` that
extractor must emit for [`oracle/LeakyOracle`](../LeakyOracle). They are the in-scope half of слой 2:
the Python side that *consumes* the graph, validated against a faithful hand-authored graph of the
real app.

## Files

- **`graph.json`** — the arch-graph of LeakyOracle: 8 internal types + the framework types they touch
  (`ownAudit/arch-graph/v1`, schema in [`docs/arch-graph.md`](../../docs/arch-graph.md)). **The
  *internal* type graph is the contract** the слой-2 extractor must reproduce. External nodes list the
  *meaningful* framework types those types reference; **pure-infrastructure BCL leaves
  (`System.Int32`, `System.Console`, `System.GC`, attributes, arrays) are elided** as
  analysis-irrelevant (external, never flaggable, never in a cycle, no effect on any rule), so a
  faithful extractor emits a **superset** of external edges — hand-authoring can't be byte-exact on BCL
  leaves and doesn't need to be. `System.String` *is* kept, because string duplication is one of the
  oracle's own smells. `test_oracle_arch.py` guards the contract against drift by checking every
  internal node points at a file that still exists under `oracle/` — it does not assert external
  completeness.
- **`rules.json`** — an **MVVM** layering profile for the oracle (the default `arch/rules.json` is
  STS-specific: `Sts.*` / SQL / WPF). Allowed direction: `Views → ViewModels → Services`; the reverse
  is forbidden. Demonstrates the rules engine is configurable per codebase, not STS-hardcoded.
- **`test_oracle_arch.py`** — runs the pass both directions (below). Wired into CI (normal + `-O`).

## What it proves

**Clean (faithful graph) → 0 findings.** The oracle is well-layered MVVM, so `arch/` correctly
reports nothing. Its real smells are *lifetime/heap* — the subscription leak (OWN001), duplicated
strings, killed virtualization (XAML107) — which are not architecture findings. This guards against
`arch/` crying wolf on clean code.

**Degraded (one planted edge) → 3 findings.** Adding a single MVVM inversion — a view-model reaching
back to a view (`WatchlistViewModel → MainWindow`) — lights up three distinct rule classes at once:

| rule | what it caught |
|---|---|
| `ARCH-MVVM-VM-VIEW` | the forbidden direction: `WatchlistViewModel → MainWindow` |
| `ARCH-CYCLE-TYPE` | the type cycle it creates: {`MainWindow`, `WatchlistViewModel`} |
| `ARCH-CYCLE-NS` | the namespace cycle: {`LeakyOracle.ViewModels`, `LeakyOracle.Views`} |

The test keeps the degraded graph in-memory (clean graph + one documented edge) so there's a single
source of truth and the regression can't silently drift from the contract.

## Run

```bash
PYTHONPATH=. python3 oracle/fixtures/test_oracle_arch.py
# or the pass directly:
PYTHONPATH=. python3 -m arch.cli --graph oracle/fixtures/graph.json --rules oracle/fixtures/rules.json
#   → architecture pass: 0 findings (clean)
```

When слой 2 lands in Own.NET, its extractor run over LeakyOracle should reproduce the **internal**
subgraph of `graph.json` (up to ids/loc; it may surface more framework-leaf edges), and this same
`arch/` pass will then run on *extracted* data instead of hand-authored — the contract makes that swap
mechanical.
