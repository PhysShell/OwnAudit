"""Architecture Drift Report CLI (Own.NET Auditor docs/own-net-auditor.md §3, phase 4):

    # snapshot main's architecture once (on the stand, from main's graph.json):
    python3 -m arch.drift_cli --graph sts_audit/graph.json --save-snapshot \
        --snapshot sts_audit/arch-snapshot.json

    # on a PR, diff the PR's graph against that snapshot:
    python3 -m arch.drift_cli --baseline sts_audit/arch-snapshot.json \
        --graph sts_audit/graph.json [--gate-level high]

Writes drift.json + drift.md (PR-friendly) to --out-dir. --baseline accepts either a saved
snapshot or a raw graph.json. Report-only by default; --gate-level fails the build (exit 2) on
drift at/above that risk. Build-free, no .NET.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .graph import Graph
from . import drift as D
from .rules import load_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🔵", "info": "⚪"}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"error: cannot read {path!r}: {e}", file=sys.stderr)
        raise SystemExit(2) from None


def _drift_md(d: dict, passed: bool, gate_level: str | None) -> str:
    c = D.counts(d)
    headline = (f"**{c['high']} High · {c['medium']} Medium · {c['low']} Low · {c['info']} info** "
                f"architecture change(s) vs baseline.")
    verdict = ""
    if gate_level:
        verdict = (f"\n✅ **PASS** — no drift at/above `{gate_level}`.\n" if passed
                   else f"\n❌ **FAIL** — drift at/above `{gate_level}` blocks the gate.\n")

    def section(risk, title):
        rows = [i for i in d["items"] if i["risk"] == risk]
        if not rows:
            return ""
        body = "\n".join(f"- {i['detail']}" for i in rows)
        return f"\n### {_EMOJI[risk]} {title} ({len(rows)})\n\n{body}\n"

    body = (section("high", "High") + section("medium", "Medium")
            + section("low", "Low") + section("info", "Info / improvements"))
    if not d["items"]:
        body = "\n_No architecture drift vs baseline._\n"
    return (
        f"# Own.NET Audit — architecture drift\n\n"
        f"{headline}\n{verdict}\n"
        f"| | count |\n|---|---|\n"
        f"| new dependencies | {d['new_edges']:,} |\n| removed dependencies | {d['removed_edges']:,} |\n"
        f"| **new cycles** | **{d['new_cycles']:,}** |\n| resolved cycles | {d['resolved_cycles']:,} |\n"
        f"| components (base → cur) | {d['base_components']:,} → {d['cur_components']:,} |\n"
        f"{body}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="arch.drift",
                                 description="Own.NET Auditor — architecture drift report")
    ap.add_argument("--graph", default=os.path.join(ROOT, "sts_audit", "graph.json"),
                    help="current graph.json (the PR's)")
    ap.add_argument("--baseline", default=os.path.join(ROOT, "sts_audit", "arch-snapshot.json"),
                    help="baseline snapshot OR a baseline graph.json")
    ap.add_argument("--snapshot", default=None,
                    help="where --save-snapshot writes (default: --baseline path)")
    ap.add_argument("--save-snapshot", action="store_true",
                    help="write a compact snapshot of --graph and exit")
    ap.add_argument("--rules", default=None, help="rules file for the drift config (default: arch/rules.json)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "arch", "out"))
    ap.add_argument("--gate-level", choices=("low", "medium", "high"), default=None,
                    help="fail (exit 2) on drift at/above this risk (default: report-only)")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.graph):
        print(f"error: no graph file at {args.graph!r} (see docs/arch-graph.md).", file=sys.stderr)
        raise SystemExit(2)
    key = (load_rules(args.rules).get("drift") or {}).get("level", "namespace")

    if args.save_snapshot:
        snap = D.snapshot(Graph.load(args.graph), key)
        dest = args.snapshot or args.baseline
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=1)
        print(f"wrote snapshot {dest}  ({len(snap['components'])} components, "
              f"{len(snap['edges'])} dep-edges, {len(snap['cycles'])} cycles)")
        return 0

    if not os.path.exists(args.baseline):
        print(f"error: no baseline at {args.baseline!r}; create one with --save-snapshot "
              f"from main's graph.", file=sys.stderr)
        return 2

    cfg = load_rules(args.rules).get("drift") or {}
    base = D.as_snapshot(_load_json(args.baseline), key)
    cur = D.snapshot(Graph.load(args.graph), key)
    d = D.diff(base, cur, cfg)
    passed, blocking = (True, [])
    if args.gate_level:
        passed, blocking = D.gate(d, args.gate_level)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "drift.json"), "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2)
    with open(os.path.join(args.out_dir, "drift.md"), "w", encoding="utf-8") as fh:
        fh.write(_drift_md(d, passed, args.gate_level))

    c = D.counts(d)
    print(f"drift: {c['high']} high, {c['medium']} medium, {c['low']} low, {c['info']} info "
          f"({d['new_cycles']} new cycle(s), {d['new_edges']} new dep(s))"
          + (f"; gate@{args.gate_level}: {'PASS' if passed else 'FAIL'}" if args.gate_level else ""))
    return 2 if (args.gate_level and not passed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
