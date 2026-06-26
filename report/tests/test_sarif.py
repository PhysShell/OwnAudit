"""SARIF exporter tests (docs/own-net-auditor.md phase 1). Bare python3 or pytest:

    PYTHONPATH=. python3 report/tests/test_sarif.py

Proves the transform is GitHub-valid and honest: one run per tool, rules deduped with
correct ruleIndex, severity mapped by category, startLine clamped, fingerprints stable
and line-independent, suppressions passed through, and min_level/max_results actually
filter. -O-safe (explicit raises, no bare assert).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from report import cli                                                            # noqa: E402
from report.sarif import (                                                        # noqa: E402
    to_sarif, _fingerprint, FINGERPRINT_KEY, SARIF_VERSION, GITHUB_MAX_RESULTS_PER_RUN,
)


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _f(tool, rule, path, line, cat, message="m", **extra):
    d = {"tool": tool, "rule": rule, "path": path, "line": line, "category_name": cat,
         "message": message}
    d.update(extra)
    return d


SAMPLE = [
    _f("own-check", "OWN001", "Broker/A.xaml.cs", 72, "subscription-leak", "event subscribed"),
    _f("own-check", "OWN001", "Broker/B.xaml.cs", 10, "subscription-leak", "event subscribed"),
    _f("roslyn", "INPC020", "Broker/A.xaml.cs", 5, "inpc-correctness", "raise for property"),
    _f("roslyn", "RCS1037", "Broker/C.cs", 0, "general-quality", "trailing whitespace"),
    _f("codeql", "cs/useless-assignment-to-local", "Core/X.cs", 9, "general-quality", "dead store"),
]


def _runs_by_tool(sarif):
    return {r["tool"]["driver"]["name"]: r for r in sarif["runs"]}


def test_top_level_shape():
    s = to_sarif(SAMPLE)
    _expect(s["version"] == SARIF_VERSION, s["version"])
    _expect(s["$schema"].endswith("sarif-2.1.0.json"), s["$schema"])
    # one run per tool present in the findings
    names = {r["tool"]["driver"]["name"] for r in s["runs"]}
    _expect("own-check (OwnAudit)" in names and "CodeQL" in names, names)
    _expect(len(s["runs"]) == 3, len(s["runs"]))


def test_rules_deduped_with_correct_index():
    s = to_sarif(SAMPLE)
    own = _runs_by_tool(s)["own-check (OwnAudit)"]
    # two OWN001 findings -> one rule, both results point at ruleIndex 0
    _expect(len(own["tool"]["driver"]["rules"]) == 1, own["tool"]["driver"]["rules"])
    _expect(all(r["ruleIndex"] == 0 and r["ruleId"] == "OWN001" for r in own["results"]),
            own["results"])


def test_level_mapping_by_category():
    s = to_sarif(SAMPLE)
    own = _runs_by_tool(s)["own-check (OwnAudit)"]["results"][0]
    roslyn = _runs_by_tool(s)["Roslyn analyzers"]["results"]
    _expect(own["level"] == "error", own["level"])                       # subscription-leak
    by_rule = {r["ruleId"]: r["level"] for r in roslyn}
    _expect(by_rule["INPC020"] == "warning", by_rule)                    # inpc-correctness
    _expect(by_rule["RCS1037"] == "note", by_rule)                       # general-quality


def test_location_region_clamped():
    s = to_sarif(SAMPLE)
    roslyn = _runs_by_tool(s)["Roslyn analyzers"]["results"]
    rcs = next(r for r in roslyn if r["ruleId"] == "RCS1037")
    region = rcs["locations"][0]["physicalLocation"]["region"]
    _expect(region["startLine"] == 1, region)                            # line 0 -> 1
    uri = rcs["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    _expect(uri == "Broker/C.cs", uri)


def test_fingerprint_stable_and_line_independent():
    a = _f("roslyn", "INPC020", "Broker/A.xaml.cs", 5, "inpc-correctness", "raise for 'Foo'")
    b = _f("roslyn", "INPC020", "Broker/A.xaml.cs", 999, "inpc-correctness", "raise for 'Foo'")
    c = _f("roslyn", "INPC020", "Broker/Other.cs", 5, "inpc-correctness", "raise for 'Foo'")
    _expect(_fingerprint(a) == _fingerprint(b), "line must not change the fingerprint")
    _expect(_fingerprint(a) != _fingerprint(c), "different path must change it")
    # surfaced on the result for GitHub correlation
    s = to_sarif([a])
    res = s["runs"][0]["results"][0]
    _expect(FINGERPRINT_KEY in res["partialFingerprints"], res["partialFingerprints"])


def test_suppression_passthrough():
    sup = _f("roslyn", "INPC020", "Broker/A.xaml.cs", 5, "inpc-correctness",
             suppressed=True, suppress_reason="by design")
    s = to_sarif([sup])
    res = s["runs"][0]["results"][0]
    _expect(res["suppressions"][0]["kind"] == "inSource", res.get("suppressions"))
    _expect(res["suppressions"][0]["justification"] == "by design", res["suppressions"])


def test_min_level_filters_below_threshold():
    s = to_sarif(SAMPLE, min_level="warning")
    levels = [r["level"] for run in s["runs"] for r in run["results"]]
    _expect(levels and all(lv in ("warning", "error") for lv in levels), levels)
    # the two general-quality 'note' findings are gone; codeql run becomes empty
    codeql = _runs_by_tool(s)["CodeQL"]
    _expect(codeql["results"] == [], codeql["results"])


def test_max_results_caps_and_records_drop():
    s = to_sarif(SAMPLE, max_results_per_run=1)
    own = _runs_by_tool(s)["own-check (OwnAudit)"]
    _expect(len(own["results"]) == 1, own["results"])
    _expect(own["properties"]["dropped"] == 1, own["properties"])
    _expect(own["properties"]["resultCount"] == 2, own["properties"])    # before the cap


def test_tier_in_properties():
    s = to_sarif(SAMPLE)
    own = _runs_by_tool(s)["own-check (OwnAudit)"]["results"][0]
    _expect(own["properties"]["tier"] == "T4", own["properties"])         # OWN -> T4
    codeql = _runs_by_tool(s)["CodeQL"]["results"][0]
    _expect(codeql["properties"]["tier"] == "T3", codeql["properties"])   # cs/* -> T3


def test_to_sarif_rejects_bad_args():
    raised = 0
    try:
        to_sarif([], min_level="warn")          # not a valid level
    except ValueError:
        raised += 1
    try:
        to_sarif([], max_results_per_run=-1)    # negative cap
    except ValueError:
        raised += 1
    _expect(raised == 2, raised)


def test_duplicate_findings_get_distinct_fingerprints():
    # same rule+path+message at different lines must not collapse to one alert
    dup = [_f("own-check", "OWN001", "Broker/A.xaml.cs", 72, "subscription-leak", "same msg"),
           _f("own-check", "OWN001", "Broker/A.xaml.cs", 130, "subscription-leak", "same msg")]
    s = to_sarif(dup)
    fps = [r["partialFingerprints"][FINGERPRINT_KEY] for r in s["runs"][0]["results"]]
    _expect(len(set(fps)) == 2, fps)                         # distinct per occurrence
    _expect(fps[0] == _fingerprint(dup[0]), "first occurrence keeps the stable base")


def test_default_cap_is_github_limit():
    _expect(GITHUB_MAX_RESULTS_PER_RUN == 25000, GITHUB_MAX_RESULTS_PER_RUN)


def test_cli_rejects_negative_max_results():
    # a bad CLI value is an argparse usage error (SystemExit), not a traceback
    raised = False
    try:
        cli.main(["--findings", "/dev/null", "--max-results", "-1"])
    except SystemExit:
        raised = True
    _expect(raised, "negative --max-results should exit via argparse")


def test_cli_writes_artifacts_with_consistent_export_block():
    d = tempfile.mkdtemp(prefix="report-")
    try:
        fp = os.path.join(d, "findings.json")
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump({"findings": SAMPLE}, fh)
        out = os.path.join(d, "out")
        rc = cli.main(["--findings", fp, "--out-dir", out, "--min-level", "warning"])
        _expect(rc == 0, rc)
        m = json.load(open(os.path.join(out, "metrics.json"), encoding="utf-8"))
        _expect(m["total"] == len(SAMPLE), m["total"])               # corpus total
        s = json.load(open(os.path.join(out, "ownnet-audit.sarif"), encoding="utf-8"))
        emitted = sum(len(r["results"]) for r in s["runs"])
        # export block records exactly what went to SARIF, so artifacts can't disagree
        _expect(m["export"]["min_level"] == "warning", m["export"])
        _expect(m["export"]["sarif_results"] == emitted, (m["export"], emitted))
        _expect(os.path.exists(os.path.join(out, "report.md")), "report.md written")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- bare-python runner ----------------------------------------------------

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
