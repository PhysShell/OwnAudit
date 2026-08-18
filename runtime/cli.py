"""Runtime correlation CLI (Own.NET Auditor docs/own-net-auditor.md §3, phase 5):

    # on the Windows stand, the heap-dump collector writes sts_audit/runtime.json after a
    # scenario (contract: docs/runtime-contract.md), then:
    python3 -m runtime.cli --findings sts_audit/findings.json --runtime sts_audit/runtime.json

Writes runtime-findings.json (confirmed leaks in findings.json shape, ready for SARIF/dashboard)
and runtime-report.md (confirmed / static-only / runtime-only). Report-only by default;
--gate-level fails the build (exit 2) on a confirmed leak at/above that confidence. No .NET.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import correlate as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path, key=None):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data[key] if key else data
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot read {path!r}: {e}", file=sys.stderr)
        raise SystemExit(2) from None


#: Everything this pass publishes. Listed once so invalidation cannot drift out
#: of step with publication and leave one stale file behind.
OUTPUTS = ("runtime-findings.json", "runtime-report.md")


def _clear_outputs(out_dir: str) -> None:
    """Remove this pass's published outputs, so the directory never describes an
    earlier run as if it were this one.

    Runs before the outcome is known, and before every exit path. Yesterday's
    runtime-report.md surviving today's refusal is the same lie in a slower
    form: nothing in the file says which run produced it, so a reader takes it
    for the current one. "Wrote no new false evidence" is not enough while the
    old evidence stays in place to be read as new."""
    for name in OUTPUTS:
        try:
            os.remove(os.path.join(out_dir, name))
        except FileNotFoundError:
            pass


def _publish(out_dir: str, name: str, text: str) -> None:
    """Write via a temp file in the same directory, then os.replace — atomic on
    POSIX and Windows, so a reader never sees a half-written report."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _report_md(res: dict, dump: dict, passed: bool, gate_level: str | None) -> str:
    conf, so, ro = res["confirmed"], res["static_only"], res["runtime_only"]
    by_conf = {"high": 0, "medium": 0}
    for f in conf:
        by_conf[f.get("confidence", "medium")] = by_conf.get(f.get("confidence", "medium"), 0) + 1
    verdict = ""
    if gate_level:
        verdict = (f"\n✅ **PASS** — no confirmed leak at/above `{gate_level}`.\n" if passed
                   else f"\n❌ **FAIL** — confirmed leak at/above `{gate_level}`.\n")

    def rows(items, render):
        return "\n".join(render(f) for f in items) or "_(none)_"
    confirmed_tbl = rows(conf, lambda f:
                         f"- **{f.get('confidence')}** — {f['message']}")
    static_tbl = rows(so, lambda f:
                      f"- `{f.get('rule')}` {f.get('resource')} — {f.get('path')}:{f.get('line', '')}")
    runtime_tbl = rows(ro, lambda f: f"- {f['message']}")
    return (
        f"# Own.NET Audit — runtime correlation\n\n"
        f"Scenario: _{dump.get('scenario', 'n/a')}_"
        + (f" ({dump.get('iterations')}×)" if dump.get("iterations") else "") + "\n\n"
        f"**{by_conf['high']} high · {by_conf['medium']} medium** confirmed · "
        f"{len(so)} static-only (suspect FP) · {len(ro)} runtime-only (blind spot).\n"
        f"{verdict}\n"
        f"## ✅ Confirmed leaks (static × runtime agree)\n\n{confirmed_tbl}\n\n"
        f"## ⚠️ Static-only (no runtime retention — likely FP or path not exercised)\n\n{static_tbl}\n\n"
        f"## 🕳️ Runtime-only (retention the static pass missed)\n\n{runtime_tbl}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="runtime.cli",
                                 description="Own.NET Auditor — runtime leak correlation")
    ap.add_argument("--findings", default=os.path.join(ROOT, "sts_audit", "findings.json"))
    ap.add_argument("--runtime", default=os.path.join(ROOT, "sts_audit", "runtime.json"),
                    help="heap-dump artifact from the stand (docs/runtime-contract.md)")
    ap.add_argument("--config", default=None, help="correlation config (default: runtime/config.json)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "runtime", "out"))
    ap.add_argument("--gate-level", choices=("medium", "high"), default=None,
                    help="fail (exit 2) on a confirmed leak at/above this confidence")
    args = ap.parse_args(argv)

    # Before ANY exit path, not just the correlation refusal: a missing dump, an
    # unreadable findings file and a not_evaluated record all end this run
    # without a result, and all of them would otherwise leave the previous run's
    # report in place to be read as this one's.
    _clear_outputs(args.out_dir)

    if not os.path.isfile(args.runtime):
        print(f"error: no runtime dump at {args.runtime!r}; collect one on the stand "
              f"(see docs/runtime-contract.md).", file=sys.stderr)
        raise SystemExit(2)

    static = _load(args.findings, key="findings")
    dump = _load(args.runtime)

    try:
        res = C.correlate(static, dump, C.load_config(args.config))
    except C.UnusableRuntimeRecord as e:
        # No report is the correct output here. A three-way split computed from a
        # run that never looked would file every static finding under "static-only
        # (suspect FP)" — a verdict on evidence that does not exist.
        print(f"error: {args.runtime!r} records no usable evaluation: {e}", file=sys.stderr)
        raise SystemExit(2) from None
    passed, blocking = (True, [])
    if args.gate_level:
        passed, blocking = C.gate(res, args.gate_level)

    # Publish atomically, so a crash between the two writes cannot leave a report
    # describing findings that were never written beside it.
    _publish(args.out_dir, "runtime-findings.json",
             json.dumps({"findings": res["confirmed"] + res["runtime_only"]}, indent=2))
    _publish(args.out_dir, "runtime-report.md", _report_md(res, dump, passed, args.gate_level))

    print(f"runtime: {len(res['confirmed'])} confirmed, {len(res['static_only'])} static-only, "
          f"{len(res['runtime_only'])} runtime-only"
          + (f"; gate@{args.gate_level}: {'PASS' if passed else 'FAIL'} "
             f"({len(blocking)} blocking)" if args.gate_level else ""))
    return 2 if (args.gate_level and not passed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
