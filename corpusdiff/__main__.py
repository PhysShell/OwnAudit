#!/usr/bin/env python3
"""`python3 -m corpusdiff` - the differential CLI both CI jobs call.

    PYTHONPATH=. python3 -m corpusdiff BASELINE.json CANDIDATE.json \\
        [--expect corpusdiff/expectations/<slice>.json] \\
        [--json report.json] [--markdown report.md] [--no-gate]

Exit codes, chosen so a workflow can branch on them without parsing anything:

    0  the candidate differs from the baseline only in ways the expectation
       signed off (or not at all)
    1  a violation or a pin failure - the gate says no
    2  the tool could not decide: bad usage, unreadable input, a malformed
       payload, or a malformed expectation

The 2 tier matters. A differ that reported a broken expectation file as "no
differences found" would turn a configuration mistake into a green check, which
is the one outcome worse than a red one.

`--no-gate` still writes the full report and still says `verdict: fail` inside
it; it only stops the process from exiting non-zero. That is for the deliberately
non-blocking phase of a long corpus run - the evidence is identical, only the
enforcement is deferred, and the report says so rather than being quietly
softened.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .delta import STRICT, DeltaError, load as load_expectation
from .diff import compare, render_markdown
from .project import ProjectionError


def _read(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise SystemExit(f"corpusdiff: cannot read {path}: {e}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"corpusdiff: {path} is not valid JSON: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="corpusdiff",
        description="Compare two normalized-findings/v2 payloads through the "
                    "pattern, physical-anchor and coverage projections.")
    ap.add_argument("baseline", help="the normalized payload from the base side")
    ap.add_argument("candidate", help="the normalized payload from the head side")
    ap.add_argument("--expect", default=None, metavar="FILE",
                    help="a corpus-delta/v1 expectation. Without one, NO output "
                         "change is signed off (the strict default).")
    ap.add_argument("--json", dest="json_out", default="", metavar="FILE",
                    help="write the machine report")
    ap.add_argument("--markdown", dest="md_out", default="", metavar="FILE",
                    help="write the short human verdict")
    ap.add_argument("--no-gate", action="store_true",
                    help="report but do not fail the process (a deliberately "
                         "non-blocking run; the report still says 'fail')")
    args = ap.parse_args(argv)

    try:
        expect = load_expectation(args.expect) if args.expect else STRICT
    except DeltaError as e:
        print(f"corpusdiff: {e}", file=sys.stderr)
        return 2

    try:
        report = compare(_read(args.baseline), _read(args.candidate), expect)
    except ProjectionError as e:
        print(f"corpusdiff: {e}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=False),
                                       encoding="utf-8")
    if args.md_out:
        Path(args.md_out).write_text(markdown, encoding="utf-8")
    print(markdown)

    if report["verdict"] == "pass":
        return 0
    if args.no_gate:
        print("corpusdiff: --no-gate, so the violations above do not fail this run",
              file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
