"""rules_map — the rule-id → human-explanation catalog (hybrid: third-party titles
harvested from the analyzers' own docs, OWN*/XAML* hand-written in Russian).
Bare-script test per AGENTS.md: PYTHONUTF8=1 python3 report/tests/test_rules_map.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from report.rules_map import load_rules_map, describe  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s %s" % (name, detail))


rules = load_rules_map()

# 1. Third-party ids resolve with harvested titles + a helpUri.
check("ma0006-title", rules.get("MA0006", {}).get("title") == "Use String.Equals instead of equality operator")
check("rcs1001-title", rules.get("RCS1001", {}).get("title", "").startswith("Add braces"))
check("wpf0041-title", "SetCurrentValue" in rules.get("WPF0041", {}).get("title", ""))
check("inpc020-title", rules.get("INPC020", {}).get("title") == "Prefer expression body accessor")
check("idisp001-title", rules.get("IDISP001", {}).get("title") == "Dispose created")
check("ma0006-help", "meziantou" in rules.get("MA0006", {}).get("help", ""))

# 2. Own rules carry Russian explanations (title_ru + why + fix).
own1 = rules.get("OWN001", {})
check("own001-ru", own1.get("title_ru") and own1.get("why_ru") and own1.get("fix_ru"),
      "OWN001 must have title_ru/why_ru/fix_ru")
check("own014-ru", rules.get("OWN014", {}).get("title_ru"))
check("own050-ru", rules.get("OWN050", {}).get("title_ru"))

# 3. CodeQL ids get a derived title + query-help URL; compiler CS gets a learn link.
cql = describe("cs/useless-assignment-to-local", rules)
check("codeql-derived", cql["title"] == "Useless assignment to local"
      and cql["help"].endswith("cs-useless-assignment-to-local/"), str(cql))
cs = describe("CS0169", rules)
check("cs-compiler", "learn.microsoft.com" in cs["help"], str(cs))

# 4. Unknown id degrades gracefully: id echoed as title, no crash.
unk = describe("ZZZ999", rules)
check("unknown-graceful", unk["title"] == "ZZZ999" and unk.get("help") is None, str(unk))

# 5. Coverage over the real findings: ≥97% of findings must resolve to a real title.
import json  # noqa: E402
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
findings_path = os.path.join(root, "sts_audit", "findings.json")
if os.path.exists(findings_path):
    with open(findings_path, encoding="utf-8") as fh:
        findings = json.load(fh)["findings"]
    total = len(findings)
    titled = sum(1 for f in findings if describe(f.get("rule", ""), rules)["title"] != f.get("rule", ""))
    check("coverage", titled / max(total, 1) >= 0.97,
          "titled %d of %d (%.1f%%)" % (titled, total, 100.0 * titled / max(total, 1)))

print("%d/%d passed" % (PASS, PASS + len(FAIL)))
if FAIL:
    for f in FAIL:
        print("FAIL:", f)
    sys.exit(1)
