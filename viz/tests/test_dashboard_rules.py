"""Dashboard consumes the rules-map (human explanations next to rule ids) and the
runtime-confirmed retention artifact. Bare-script test per AGENTS.md:
PYTHONUTF8=1 python3 viz/tests/test_dashboard_rules.py
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)

from viz import build_dashboard  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s %s" % (name, detail))


build_dashboard.main(["viz/fixtures"])
out = os.path.join(ROOT, "viz", "sts-dashboard.html")
with open(out, encoding="utf-8") as fh:
    html = fh.read()

# 1. Rule metadata rides along with the interned rule list: harvested third-party
#    titles and the hand-written Russian for OWN rules (escaped by json.dumps).
check("rule-meta-key", '"rule_meta"' in html)
check("ma0006-title", "Use String.Equals instead of equality operator" in html)
ru = json.dumps("Подписка на событие без отписки")[1:-1]
check("own001-ru", ru in html, "expected escaped RU title for OWN001")

# 2. The runtime-confirmed panel exists and carries the retained types + their roots.
check("runtime-card", 'id="runtime"' in html)
check("runtime-key", '"runtime"' in html)
check("runtime-holder", "MarketDataService" in html)
check("runtime-scenario", "open+close 50 screens (fixture)" in html)

# 3. Zero-count entries do not clutter the panel data.
check("runtime-skips-clean", "FixedWatchlistViewModel" not in html)

print("%d/%d passed" % (PASS, PASS + len(FAIL)))
if FAIL:
    for f in FAIL:
        print("FAIL:", f)
    sys.exit(1)
