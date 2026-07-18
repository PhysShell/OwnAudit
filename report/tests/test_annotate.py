"""annotate_cli — enrich a health-report.md findings list with the rule id + its
human explanation (joined from findings.json by path:line) and append a rule legend.
Bare-script test: PYTHONUTF8=1 python3 report/tests/test_annotate.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from report.annotate_cli import annotate  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s %s" % (name, detail))


REPORT = """# Own.NET Audit — health report — `X`

## Candidates — 2 (single tool: unique catch or possible FP)

- `Broker/MainWindow.xaml.cs:3957` **[P1 · subscription-leak]** (own-check)
- `Broker/Util.cs:10` **[P2 · quality]** (meziantou)

## Coverage / honesty
"""

FINDINGS = {"findings": [
    {"rule": "OWN001", "path": "Broker/MainWindow.xaml.cs", "line": 3957,
     "category_name": "subscription-leak", "tool": "own-check", "suppressed": False},
    {"rule": "MA0006", "path": "Broker/Util.cs", "line": 10,
     "category_name": "quality", "tool": "meziantou", "suppressed": False},
]}

with tempfile.TemporaryDirectory() as td:
    rp = os.path.join(td, "health-report.md")
    fp = os.path.join(td, "findings.json")
    op = os.path.join(td, "health-report.annotated.md")
    open(rp, "w", encoding="utf-8").write(REPORT)
    json.dump(FINDINGS, open(fp, "w", encoding="utf-8"))

    annotate(rp, fp, op)
    out = open(op, encoding="utf-8").read()

    # finding lines gain the rule id and its human title, RU included for OWN rules
    check("own001-inline", "OWN001" in out and "Подписка на событие без отписки" in out)
    check("ma0006-inline", "MA0006" in out and "Use String.Equals instead of equality operator" in out)

    # a legend appendix lists every referenced rule once, with the doc link when known
    check("legend-section", "## Rule legend" in out)
    check("legend-link", "meziantou/Meziantou.Analyzer" in out)

    # untouched sections survive verbatim
    check("keeps-structure", "## Coverage / honesty" in out)

print("%d/%d passed" % (PASS, PASS + len(FAIL)))
if FAIL:
    for f in FAIL:
        print("FAIL:", f)
    sys.exit(1)
