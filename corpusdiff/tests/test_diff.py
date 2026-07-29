"""`corpusdiff` differential tests. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/tests/test_diff.py

Every case here goes through the REAL normalizer: the fixtures are SARIF, they
are written to disk, and `aggregate.normalize.build_payload` turns them into the
payloads the differ reads. A differ tested against hand-written payloads would be
tested against this file's idea of what a normalized finding looks like, not
against the one the pipeline actually produces - and the seam between them is
exactly where a projection quietly stops seeing a field.

WHAT IS PINNED
--------------
The four contract questions of the startColumn slice:

  * an old run and a new run over one corpus produce the SAME pattern projection
    and the SAME pattern multiplicity - only the physical anchor moves;
  * that move passes under the checked-in expectation, and FAILS with no
    expectation, because silence is not a signature;
  * the shapes that are not this slice - a line moving, a path moving, a finding
    appearing or vanishing, a multiplicity change, a column being LOST - are
    violations under the same expectation;
  * a column that is not information (one constant everywhere; one column shared
    by two findings a column exists to tell apart) is a violation that NO
    expectation can sign off.

And the rule the whole design rests on: `occurrence_id` is never compared
directly. Two genuine runs carry different `producer_run_id`s and therefore
different occurrence ids, by contract. A differ that compared them would report
that contract working as a total regression on every run.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from aggregate.normalize import build_payload, load_taxonomy                     # noqa: E402
from corpusdiff.delta import STRICT, DeltaError, load as load_expectation, parse  # noqa: E402
from corpusdiff.diff import compare, render_markdown                             # noqa: E402
from corpusdiff.project import ProjectionError, anchor_projection                # noqa: E402
from corpusdiff.project import pattern_multiplicity, pattern_projection          # noqa: E402

EXPECTATION = os.path.join(ROOT, "corpusdiff", "expectations",
                           "own-check-start-column.json")

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


# --------------------------------------------------------------------------- #
# Fixture construction                                                        #
# --------------------------------------------------------------------------- #

def result(rule: str, msg: str, uri: str, line: int, col: int | None = None) -> dict:
    """One own-check-shaped SARIF result. `col=None` omits `startColumn` entirely -
    the pre-slice shape, and the thing the slice fills in. It is NOT emitted as 0
    or 1: SARIF columns are 1-based, so there is no in-band 'not reported' value,
    and a substituted 1 is indistinguishable from a real first-column finding."""
    region: dict = {"startLine": line}
    if col is not None:
        region["startColumn"] = col
    return {"ruleId": rule, "level": "warning", "message": {"text": msg},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": uri}, "region": region}}]}


def sarif(results: list[dict]) -> str:
    return json.dumps({"version": "2.1.0",
                       "runs": [{"tool": {"driver": {"name": "Owen"}},
                                 "results": results}]})


SUB = "event subscribed but never unsubscribed [resource: subscription token]"
TIMER = "timer never stopped [resource: timer]"
FIELD = "field never disposed [resource: disposable field]"


def baseline_results() -> list[dict]:
    """The pre-slice corpus: real lines, no columns anywhere.

    Deliberately includes the shapes the mini corpus is built around - a
    subscription, a timer, a disposable field, TWO findings on one line, an
    advisory coverage note, and a third-party finding that normalization
    suppresses - so the projections are exercised over the same population the
    CI job will see rather than over three easy rows.
    """
    return [
        result("OWN001", SUB, "src/Vm/CustomerViewModel.cs", 12),
        result("OWN001", TIMER, "src/Vm/TimerViewModel.cs", 30),
        result("OWN001", FIELD, "src/Vm/ReportViewModel.cs", 7),
        # two DIFFERENT findings anchored on one line: the case a column exists for
        result("OWN001", SUB, "src/Vm/TwoOnOneLine.cs", 42),
        result("OWN014", "region escape: promoted to App lifetime",
               "src/Vm/TwoOnOneLine.cs", 42),
        # an advisory coverage note (OWN050): counted in the ledger, absent from
        # `findings`, so it is compared through the advisory census
        result("OWN050", "cannot verify 'X.Y' - unresolved [resource: unresolved "
                         "reference]", "src/Util/Unknown.cs", 3),
        # a third-party finding: baseline-suppressed, compared through the
        # suppression census for the same reason
        result("OWN001", FIELD, "DevExpress.Xpf/Grid/Helper.cs", 4),
    ]


def with_columns(results: list[dict], columns: list[int | None]) -> list[dict]:
    """The same results, each given (or not given) a column. Length-checked: a
    short list would silently leave the tail uncolumned and make a test pass for
    the wrong reason."""
    if len(results) != len(columns):
        raise ValueError(f"{len(results)} results but {len(columns)} columns")
    out = []
    for res, col in zip(results, columns):
        clone = json.loads(json.dumps(res))
        if col is not None:
            clone["locations"][0]["physicalLocation"]["region"]["startColumn"] = col
        out.append(clone)
    return out


#: Real, distinct columns for `baseline_results()`, in order. The two findings on
#: line 42 get DIFFERENT columns - that is the discrimination the field is for.
REAL_COLUMNS: list[int | None] = [9, 13, 21, 17, 44, 5, 9]


def payload(results: list[dict], tmp: str, name: str,
            run_id: str | None = None) -> dict:
    """Normalize one side into a `normalized-findings/v2` payload.

    `run_id` writes a provenance manifest so occurrence ids are actually minted.
    `input_digest` is null on purpose here: the manifest's job in these tests is
    to supply run identity, and a digest would only pin bytes this test just
    wrote.
    """
    path = os.path.join(tmp, f"{name}.sarif")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(sarif(results))
    manifest_path = None
    if run_id is not None:
        manifest_path = os.path.join(tmp, f"{name}-manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": "producer-provenance/v1",
                       "inputs": {"own-check": {
                           "producer_run_id": run_id,
                           "producer_name": "own-check",
                           "producer_version": None, "input_digest": None,
                           "config_digest": None, "source_commit": None}}}, fh)
    return build_payload([("own-check", path)], load_taxonomy(), [], manifest_path)


# --------------------------------------------------------------------------- #
# Cases                                                                       #
# --------------------------------------------------------------------------- #

def main() -> int:
    expect = load_expectation(EXPECTATION)
    with tempfile.TemporaryDirectory() as tmp:
        base = payload(baseline_results(), tmp, "base")
        cand = payload(with_columns(baseline_results(), REAL_COLUMNS), tmp, "cand")

        # 0. The fixture is not vacuous: the suppressed and advisory findings really
        #    are out of `findings` and counted in the ledger, and five scored
        #    findings really did survive. Without this the census comparisons below
        #    would be comparing two empty dicts and passing.
        check(len(base["findings"]) == 5,
              f"expected 5 scored findings in the fixture, got {len(base['findings'])}")
        check(base["coverage"]["suppressed"] == 1,
              "the fixture must carry exactly one suppressed (third-party) finding")
        check(base["coverage"]["analysis_skipped"] == 1,
              "the fixture must carry exactly one advisory coverage note (OWN050)")

        # 1. An identical run against itself: no differences in any projection, and
        #    it passes even under the STRICT default (nothing was signed off because
        #    nothing changed).
        same = compare(base, base, STRICT)
        check(same["verdict"] == "pass", f"identical runs must pass: {same['totals']}")
        check(same["totals"]["changes"] == 0,
              f"identical runs must report no changes: {same['totals']['by_kind']}")

        # 2. THE SLICE. Columns appear; the pattern projection is untouched.
        b_pat, c_pat = pattern_projection(base), pattern_projection(cand)
        check(b_pat["rows"] == c_pat["rows"],
              "the pattern projection must be identical across the slice - only the "
              "physical anchor may move")
        check(pattern_multiplicity(b_pat) == pattern_multiplicity(c_pat),
              "pattern multiplicity must be identical across the slice")
        check(anchor_projection(base)["sites"] != anchor_projection(cand)["sites"],
              "the anchor projection MUST differ, or the fixture does not exercise "
              "the slice at all")

        rep = compare(base, cand, expect)
        check(rep["verdict"] == "pass",
              f"the startColumn slice must pass its own expectation: "
              f"{[v['kind'] for v in rep['violations']]} pins={rep['pin_failures']}")
        check(rep["totals"]["by_kind"].get("start_column_change", {}).get("allowed") == 5,
              f"expected 5 allowed column transitions, got "
              f"{rep['totals']['by_kind']}")
        check(rep["totals"]["violations"] == 0 and rep["totals"]["pin_failures"] == 0,
              "the slice must produce neither violations nor pin failures")
        cov = rep["coverage"]
        check(cov["baseline"]["by_producer"]["own-check"]["with_start_column"] == 0,
              "the baseline must report no columns")
        check(cov["candidate"]["by_producer"]["own-check"]["with_start_column"] == 5,
              "the candidate must report a column for every scored finding")
        check(cov["delta"]["scalars"]["total_findings"] == 0,
              "the slice must not change the finding count")
        check(cov["delta"]["scalars"]["pattern_count"] == 0,
              "the slice must not change the pattern count")
        check(cov["delta"]["scalars"]["ambiguous_anchors"] <= 0,
              "the slice must not increase ambiguity")

        # 3. The SAME change with no expectation is a failure. Silence is not a
        #    signature: an undeclared output change is exactly what the gate is for.
        strict = compare(base, cand, STRICT)
        check(strict["verdict"] == "fail",
              "an undeclared column change must fail the strict default")
        check(all("no corpus-delta/v1 expectation" in v["why"]
                  for v in strict["violations"]),
              "the strict failure must say WHY - that nothing was signed off")

        # 4. A line that moved. Forbidden by the expectation AND a pin failure, and
        #    the columns on the moved line are NOT additionally reported: there is no
        #    occurrence correspondence left to compare them through.
        moved = with_columns(baseline_results(), REAL_COLUMNS)
        moved[0]["locations"][0]["physicalLocation"]["region"]["startLine"] = 13
        rep4 = compare(base, payload(moved, tmp, "moved"), expect)
        check(rep4["verdict"] == "fail", "a moved line must fail")
        kinds4 = [v["kind"] for v in rep4["violations"]]
        check("line_change" in kinds4, f"expected a line_change violation, got {kinds4}")
        check([p["pin"] for p in rep4["pin_failures"]] == ["start_line"],
              f"expected exactly the start_line pin to fail: {rep4['pin_failures']}")
        moved_change = next(v for v in rep4["violations"] if v["kind"] == "line_change")
        check(moved_change["before"] == {"12": 1} and moved_change["after"] == {"13": 1},
              f"the line_change must carry both line censuses: {moved_change}")

        # 5. A finding that vanished: a removed pattern, plus the population and
        #    count pins.
        fewer = with_columns(baseline_results(), REAL_COLUMNS)[1:]
        rep5 = compare(base, payload(fewer, tmp, "fewer"), expect)
        check(rep5["verdict"] == "fail", "a vanished finding must fail")
        check("removed_pattern" in [v["kind"] for v in rep5["violations"]],
              f"expected removed_pattern: {[v['kind'] for v in rep5['violations']]}")
        check({p["pin"] for p in rep5["pin_failures"]} == {"pattern_population",
                                                          "finding_count"},
              f"expected the population and count pins to fail: {rep5['pin_failures']}")

        # 6. A finding that appeared.
        more = with_columns(baseline_results(), REAL_COLUMNS) + [
            result("OWN001", SUB, "src/Vm/BrandNew.cs", 5, 11)]
        rep6 = compare(base, payload(more, tmp, "more"), expect)
        check("new_pattern" in [v["kind"] for v in rep6["violations"]],
              f"expected new_pattern: {[v['kind'] for v in rep6['violations']]}")

        # 7. A path that moved. `pattern_id` hashes the path, so this arrives as one
        #    pattern vanishing and an unrelated one appearing; it must be paired back
        #    up and reported as what it is, ONCE, with both spellings.
        renamed = with_columns(baseline_results(), REAL_COLUMNS)
        renamed[1]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = \
            "src/Vm/Renamed/TimerViewModel.cs"
        rep7 = compare(base, payload(renamed, tmp, "renamed"), expect)
        kinds7 = [v["kind"] for v in rep7["violations"]]
        check(kinds7.count("path_change") == 1,
              f"a moved path must be reported exactly once as a path_change: {kinds7}")
        check("new_pattern" not in kinds7 and "removed_pattern" not in kinds7,
              f"a path change must NOT also surface as an orphan pair: {kinds7}")
        pc = next(v for v in rep7["violations"] if v["kind"] == "path_change")
        check(pc["from_path"] == "src/Vm/TimerViewModel.cs"
              and pc["to_path"] == "src/Vm/Renamed/TimerViewModel.cs",
              f"the path_change must name both spellings: {pc}")

        # 8. Every column is 1. The expectation permits null-to-positive-integer, so
        #    a naive reading signs this off - and it is the one shape that must never
        #    be signable. The producer has not learned where its findings are; it has
        #    learned to print a number.
        ones = with_columns(baseline_results(), [1] * len(baseline_results()))
        rep8 = compare(base, payload(ones, tmp, "ones"), expect)
        check(rep8["verdict"] == "fail",
              "a uniform fabricated column must fail even with the transition allowed")
        fab8 = [v for v in rep8["violations"] if v["kind"] == "fabricated_column_uniform"]
        check(len(fab8) == 1 and fab8[0]["start_column"] == 1,
              f"expected one fabricated_column_uniform for column 1: {rep8['violations']}")

        # 9. Two DIFFERENT findings on line 42 given the SAME column. The column is
        #    decoration: it costs a schema field and buys no discrimination.
        collide = with_columns(baseline_results(), [9, 13, 21, 17, 17, 5, 9])
        rep9 = compare(base, payload(collide, tmp, "collide"), expect)
        check(rep9["verdict"] == "fail", "a colliding column must fail")
        fab9 = [v for v in rep9["violations"]
                if v["kind"] == "fabricated_column_collision"]
        check(len(fab9) == 1 and fab9[0]["start_line"] == 42
              and len(fab9[0]["pattern_ids"]) == 2,
              f"expected one collision naming both patterns: {rep9['violations']}")

        # 10. The same two findings given DISTINCT columns - case 2 already proved
        #     this passes; here we prove the collision check is not simply always
        #     firing on a shared line.
        check(not [v for v in rep["violations"]
                   if v["kind"] == "fabricated_column_collision"],
              "distinct columns on one line must NOT read as a collision")

        # 11. A column that was LOST. The expectation allows absent -> present, and
        #     that is not the same permission as present -> absent.
        rep11 = compare(cand, base, expect)
        check(rep11["verdict"] == "fail", "losing a column must fail")
        lost = [v for v in rep11["violations"] if v["kind"] == "start_column_change"]
        check(len(lost) == 5
              and all(v["transition"] == "positive-integer-to-null" for v in lost),
              f"expected 5 positive-integer-to-null violations: {lost}")

        # 12. Multiplicity: the same pattern, reported twice instead of once. The
        #     population is unchanged, the count is not, and only the multiplicity
        #     comparison sees it.
        dupe = with_columns(baseline_results(), REAL_COLUMNS) + [
            result("OWN001", SUB, "src/Vm/CustomerViewModel.cs", 12, 9)]
        rep12 = compare(base, payload(dupe, tmp, "dupe"), expect)
        kinds12 = [v["kind"] for v in rep12["violations"]]
        check("multiplicity_change" in kinds12 or "line_change" in kinds12,
              f"a repeated pattern must be caught by multiplicity or line census: "
              f"{kinds12}")
        check("new_pattern" not in kinds12,
              f"a repeat of an existing pattern is not a new pattern: {kinds12}")

        # 13. The censuses. A vanished advisory note and a vanished suppression are
        #     both absent from `findings` by contract, so ONLY the ledger comparison
        #     can see them - and both are forbidden.
        no_note = [r for r in with_columns(baseline_results(), REAL_COLUMNS)
                   if r["ruleId"] != "OWN050"]
        rep13 = compare(base, payload(no_note, tmp, "no_note"), expect)
        check("advisory_census_change" in [v["kind"] for v in rep13["violations"]],
              f"a vanished coverage note must surface through the advisory census: "
              f"{[v['kind'] for v in rep13['violations']]}")
        no_sup = [r for r in with_columns(baseline_results(), REAL_COLUMNS)
                  if "DevExpress" not in
                  r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]]
        rep13b = compare(base, payload(no_sup, tmp, "no_sup"), expect)
        check("suppression_census_change" in [v["kind"] for v in rep13b["violations"]],
              f"a vanished suppression must surface through the suppression census: "
              f"{[v['kind'] for v in rep13b['violations']]}")

        # 14. THE RULE THE DESIGN RESTS ON. Two genuine runs carry different
        #     producer_run_ids, so every occurrence_id differs. That is the contract
        #     working, and the differ must not read it as a regression.
        b_ids = payload(baseline_results(), tmp, "run_a", run_id="run-a/own-check")
        c_ids = payload(with_columns(baseline_results(), REAL_COLUMNS), tmp, "run_b",
                        run_id="run-b/own-check")
        minted_b = {r["occurrence_id"] for r in b_ids["findings"]}
        minted_c = {r["occurrence_id"] for r in c_ids["findings"]}
        check(all(minted_b) and all(minted_c),
              "the fixture must actually mint occurrence ids, or case 14 is vacuous")
        check(not (minted_b & minted_c),
              "two runs must share NO occurrence id, or the run id is not in the hash")
        rep14 = compare(b_ids, c_ids, expect)
        check(rep14["verdict"] == "pass",
              f"differing occurrence ids must not be a regression: "
              f"{[v['kind'] for v in rep14['violations']]}")
        check(rep14["coverage"]["delta"]["scalars"]["with_occurrence_id"] == 0,
              "occurrence COVERAGE is what is comparable, and here it is flat")

        # 15. A malformed input is a refusal, not a clean verdict. A differ that
        #     reported bad input as "no differences" would turn a configuration
        #     mistake into a green check.
        try:
            compare({"schema_version": "normalized-findings/v1", "findings": []}, base)
        except ProjectionError:
            pass
        else:
            fails.append("a v1 payload must be refused, not compared")
        try:
            compare({"schema_version": "normalized-findings/v2",
                     "findings": [{"tool": "own-check"}]}, base)
        except ProjectionError:
            pass
        else:
            fails.append("a finding without identity must be refused")

        # 16. The blanket allowlist stays unreachable through the loading path the
        #     CLI uses, not only through `parse`.
        blanket = os.path.join(tmp, "blanket.json")
        with open(blanket, "w", encoding="utf-8") as fh:
            json.dump({"schema": "corpus-delta/v1", "allow_any_difference": True}, fh)
        try:
            load_expectation(blanket)
        except DeltaError as e:
            check("allow_any_difference" in str(e),
                  f"the refusal must name the key: {e}")
        else:
            fails.append("allow_any_difference must be refused by load(), too")

        # 17. `forbidden` outranks `allowed_changes`: an expectation cannot be
        #     talked into permitting a kind it also prohibits. (The loader rejects
        #     the self-contradictory FILE; this pins the resolution inside the
        #     Expectation object, which is what the differ actually asks.)
        both = parse({"schema": "corpus-delta/v1", "forbidden": ["start_column_change"]})
        check(not both.permits("start_column_change", "own-check",
                               "null-to-positive-integer"),
              "a forbidden kind must stay forbidden")

        # 18. The Markdown verdict is renderable for both outcomes and stays ASCII -
        #     it lands in a job summary and a PR comment.
        for name, doc in (("pass", rep), ("fail", rep8)):
            md = render_markdown(doc)
            check(md.isascii(), f"the {name} markdown must be ASCII-only")
            check(("PASS" if name == "pass" else "FAIL") in md.splitlines()[0],
                  f"the {name} markdown headline must state the verdict: "
                  f"{md.splitlines()[0]!r}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"corpusdiff/tests/test_diff: {'OK' if not fails else 'FAIL'} - "
          f"18 cases")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
