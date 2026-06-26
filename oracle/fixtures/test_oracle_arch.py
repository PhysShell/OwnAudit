"""Runs the architecture pass on the LeakyOracle golden graph. Bare python3 or pytest:

    PYTHONPATH=. python3 oracle/fixtures/test_oracle_arch.py

Two directions, both on oracle-shaped (real, not toy) data:
  * the faithful oracle graph is architecturally CLEAN — arch/ must not false-positive on a
    well-layered MVVM app (its real smells are lifetime/heap: OWN001, string-dup, XAML107);
  * a single planted MVVM inversion (a view-model reaching back to a view) must light up the
    layering rule AND both the type- and namespace-level cycle rules.

This pins the graph.json contract the слой-2 Roslyn extractor must emit for the oracle, and
anchors arch/ against a realistic regression. -O-safe (explicit raises).
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
APP_DIR = os.path.join(ROOT, "oracle", "LeakyOracle")

from arch.graph import Graph                                              # noqa: E402
from arch import rules as R                                              # noqa: E402

GRAPH = os.path.join(HERE, "graph.json")
RULES = os.path.join(HERE, "rules.json")

# the planted regression: a view-model reaching back to a view (MVVM inversion)
BACK_EDGE = {"from": "T:LeakyOracle.ViewModels.WatchlistViewModel",
             "to": "T:LeakyOracle.Views.MainWindow", "kind": "depends"}


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _run(data):
    return R.run(Graph(data), R.load_rules(RULES))


def test_clean_oracle_graph_has_no_arch_findings():
    findings = _run(json.load(open(GRAPH, encoding="utf-8")))
    _expect(findings == [], f"faithful oracle graph should be architecturally clean, got: "
                            f"{[f['rule'] for f in findings]}")


def _source_type_stems():
    # the oracle is one public type per .cs file; strip .axaml.cs / .cs to the type name.
    stems = set()
    for cs in glob.glob(os.path.join(APP_DIR, "**", "*.cs"), recursive=True):
        if f"{os.sep}obj{os.sep}" in cs or f"{os.sep}bin{os.sep}" in cs:
            continue
        base = os.path.basename(cs)
        stems.add(base[:-len(".axaml.cs")] if base.endswith(".axaml.cs") else base[:-len(".cs")])
    return stems


def test_graph_internal_nodes_track_the_oracle_sources_exactly():
    # Strong drift guard, both directions: the internal node set must equal the set of oracle
    # source types. A new view-model with no graph node (or a node for a deleted type) fails here
    # — not just "every node points at a real file", which a stale-but-incomplete graph passes.
    g = Graph(json.load(open(GRAPH, encoding="utf-8")))
    node_names = {g.name(nid) for nid in g.type_ids()}
    sources = _source_type_stems()
    _expect(node_names == sources,
            f"graph internal types and oracle sources diverged:\n"
            f"  in graph not in src: {sorted(node_names - sources)}\n"
            f"  in src not in graph: {sorted(sources - node_names)}")
    # and every internal node still anchors at a real file
    for nid in g.type_ids():
        path = g.node(nid).get("loc", {}).get("file", "")
        _expect(os.path.isfile(os.path.join(ROOT, path)),
                f"node {nid} points at missing file {path!r}")


def test_planted_mvvm_inversion_lights_up_layering_and_both_cycles():
    data = json.load(open(GRAPH, encoding="utf-8"))
    data["edges"].append(BACK_EDGE)
    by_rule = {}
    for f in _run(data):
        by_rule.setdefault(f["rule"], []).append(f)

    _expect(set(by_rule) == {"ARCH-MVVM-VM-VIEW", "ARCH-CYCLE-TYPE", "ARCH-CYCLE-NS"},
            f"one MVVM inversion should fire exactly those three rules, got {sorted(by_rule)}")

    lay = by_rule["ARCH-MVVM-VM-VIEW"][0]
    _expect(lay["resource"] == "WatchlistViewModel" and "→ MainWindow" in lay["message"], lay)
    # cycle findings name the SCC members as a set, not a fake arrow chain
    _expect("MainWindow" in by_rule["ARCH-CYCLE-TYPE"][0]["message"]
            and "WatchlistViewModel" in by_rule["ARCH-CYCLE-TYPE"][0]["message"],
            by_rule["ARCH-CYCLE-TYPE"][0])
    _expect(by_rule["ARCH-CYCLE-NS"][0]["resource"] == "LeakyOracle.ViewModels", by_rule["ARCH-CYCLE-NS"][0])


def test_findings_are_in_findings_json_shape():
    data = json.load(open(GRAPH, encoding="utf-8"))
    data["edges"].append(BACK_EDGE)
    keys = {"tool", "rule", "category_name", "resource", "path", "line", "message", "suppressed"}
    for f in _run(data):
        _expect(set(f) == keys, f"finding not in findings.json shape: {sorted(f)}")
        _expect(f["tool"] == "own-arch" and f["category_name"] == "architecture", f)


def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
