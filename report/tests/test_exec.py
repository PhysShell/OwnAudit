"""exec_cli — the Russian executive report: confirmed leaks with owners and fix
advice, the pain map, no 72k-findings noise. Bare-script test:
PYTHONUTF8=1 python3 report/tests/test_exec.py
"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)

from report.exec_cli import build  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s %s" % (name, detail))


with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, "exec-report.md")
    build(runtime_path=os.path.join(ROOT, "viz", "fixtures", "runtime-sts.json"),
          health_path=os.path.join(ROOT, "viz", "fixtures", "health-report.md"),
          out_path=out, title="STS — сводка аудита (фикстура)")
    text = open(out, encoding="utf-8").read()

    # Russian, audience = management/team: headline numbers up top.
    check("title", "STS — сводка аудита (фикстура)" in text)
    check("confirmed-count", "**2**" in text[:400], "expects 2 confirmed types in the headline")

    # every confirmed leak: type, count, the pinning owner in Russian terms.
    check("watchlist-row", "WatchlistViewModel" in text)
    check("owner", "MarketDataService.QuoteReceived" in text)
    check("kind-ru", "статическое событие" in text)
    check("timer-ru", "таймер" in text.lower())

    # the fix advice comes from rules_own.json, not ad-hoc text.
    check("fix-advice", "WeakEventManager" in text)

    # pain map carried over from the health report.
    check("pain-module", "Acme.Portfolio" in text)

    # zero-count control types stay out of the executive view, and an expected
    # survivor (count == expected) is design, not a leak.
    check("no-clean-types", "FixedWatchlistViewModel" not in text)
    check("honors-expected", "SingletonMarketService" not in text)

print("%d/%d passed" % (PASS, PASS + len(FAIL)))
if FAIL:
    for f in FAIL:
        print("FAIL:", f)
    sys.exit(1)
