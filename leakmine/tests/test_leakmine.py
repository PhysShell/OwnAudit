"""LeakFixMine pipeline tests (docs/leakfix-mine.md). Bare python3 or pytest:

    PYTHONPATH=. python3 leakmine/tests/test_leakmine.py

Covers the honest core: diff parsing, patch-signal classification (incl. penalties), SZZ
attribution + before/after correspondence + lead-time over a REAL temp git repo, the
verdict combiner (unique catch / unique miss), metrics aggregation, the over-vetted sweep
selection, and deterministic query/SQL generation. -O-safe (explicit raises, no bare assert).
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from leakmine import (  # noqa: E402
    bigquery, collect, confirm, diffparse, metrics, mine, schema, signals, sweep, szz,
)


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---- diffparse -------------------------------------------------------------------

REACT_PATCH = """diff --git a/src/Widget.tsx b/src/Widget.tsx
--- a/src/Widget.tsx
+++ b/src/Widget.tsx
@@ -10,5 +10,9 @@ export function Widget() {
   useEffect(() => {
     const onResize = () => setW(window.innerWidth);
     window.addEventListener('resize', onResize);
-  }, []);
+    return () => {
+      window.removeEventListener('resize', onResize);
+    };
+  }, []);
+  // cleanup added
 }
"""


def test_diffparse():
    fds = diffparse.parse_patch(REACT_PATCH)
    _expect(len(fds) == 1, "one file diff")
    fd = fds[0]
    _expect(fd.path == "src/Widget.tsx", f"path {fd.path}")
    added = "\n".join(fd.added_text())
    _expect("removeEventListener" in added, "added removeEventListener")
    # the fix removed old line 13 (`}, []);`) — it must register as touched.
    _expect(fd.touches_old_line(13, window=0), "old line 13 removed/replaced")
    _expect(not fd.touches_old_line(10, window=0), "context line 10 untouched")
    _expect(fd.touches_old_line(11, window=2), "window admits near line")


def test_diffparse_body_lines_with_header_prefixes():
    # a removed SQL comment renders as "--- ..." at column 0; inside the hunk budget it
    # must be body content, not misread as a file header.
    patch = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
             "@@ -1,2 +1,2 @@\n--- old comment\n+-- new comment\n SELECT 1;\n")
    fds = diffparse.parse_patch(patch)
    _expect(len(fds) == 1, f"one file, got {len(fds)}")
    _expect("-- old comment" in fds[0].removed_text(), "removed comment captured as body")
    _expect("-- new comment" in fds[0].added_text(), "added comment captured as body")


def test_diffparse_bare_multifile():
    # bare patch (no `diff --git`): the second file's "--- " must start a NEW FileDiff,
    # not overwrite the first.
    patch = ("--- a/one.py\n+++ b/one.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
             "--- a/two.py\n+++ b/two.py\n@@ -1,1 +1,1 @@\n-c\n+d\n")
    fds = diffparse.parse_patch(patch)
    _expect(len(fds) == 2, f"two files, got {len(fds)}")
    _expect({f.path for f in fds} == {"one.py", "two.py"}, f"paths {[f.path for f in fds]}")


# ---- signals ---------------------------------------------------------------------

def test_signals_react():
    cls = signals.classify("react_ts", title="Fix memory leak in Widget",
                           body="useEffect never removed the resize listener", patch=REACT_PATCH)
    _expect(cls.category == signals.SUBSCRIPTION, f"category {cls.category}")
    _expect(cls.is_likely_fix, f"likely fix, score={cls.score}")
    _expect("title:leak-keyword" in cls.evidence, "title keyword scored")


def test_signals_docs_penalty():
    docs = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n"
            "@@ -1,1 +1,2 @@\n context\n+a note about leaks\n")
    cls = signals.classify("react_ts", title="docs: mention memory leak", body="", patch=docs)
    _expect("penalty:docs-only" in cls.evidence, "docs-only penalised")
    _expect(not cls.is_candidate, f"docs-only not a candidate, score={cls.score}")


def test_signals_dotnet_event():
    patch = ("diff --git a/A.xaml.cs b/A.xaml.cs\n--- a/A.xaml.cs\n+++ b/A.xaml.cs\n"
             "@@ -5,3 +5,4 @@\n   void Wire() {\n-    svc.Tick += OnTick;\n"
             "+    svc.Tick += OnTick;\n+    Unloaded += (s,e) => svc.Tick -= OnTick;\n   }\n")
    cls = signals.classify("dotnet_wpf", title="Fix event handler leak", body="", patch=patch)
    _expect(cls.category == signals.SUBSCRIPTION, f"category {cls.category}")
    _expect(cls.is_candidate, f"candidate, score={cls.score}")


def test_signals_java_executor_single_form():
    # a fix that adds ONLY .shutdown() (not both forms) must still clear the threshold.
    patch = ("diff --git a/Svc.java b/Svc.java\n--- a/Svc.java\n+++ b/Svc.java\n"
             "@@ -5,2 +5,3 @@\n   void stop() {\n+    pool.shutdown();\n   }\n")
    cls = signals.classify("java_spring", title="fix ExecutorService memory leak", body="", patch=patch)
    _expect(cls.category == signals.TASK, f"category {cls.category}")
    _expect(cls.is_candidate, f"single-form shutdown is a candidate, score={cls.score}")


# ---- szz attribution + correspondence --------------------------------------------

def _finding(tool, rule, file, line, **kw):
    return szz.Finding(tool=tool, rule=rule, file=file, line=line, **kw)


def test_attribution_causal_vs_coincidental():
    f_on_fix = _finding("ownaudit", "OWN-EFFECT", "src/Widget.tsx", 13)
    att = szz.attribute(REACT_PATCH, f_on_fix, window=0)
    _expect(att.fix_touches, "finding on removed line is causal")

    f_elsewhere = _finding("eslint", "no-leak", "src/Widget.tsx", 200)
    att2 = szz.attribute(REACT_PATCH, f_elsewhere, window=2)
    _expect(not att2.fix_touches, "far-away finding not causal")
    _expect(att2.in_changed_file, "but still in the changed file")


def test_correspondence_confirmed_vs_lucky():
    target = _finding("ownaudit", "OWN-EFFECT", "src/Widget.tsx", 13, resolution="semantic")
    before = [target]
    after = []  # gone after
    corr = szz.correspond(before, after, REACT_PATCH, target, window=0)
    _expect(corr.confirmed_catch, "flagged before, gone after, causal -> confirmed")

    # coincidental: finding far from the fix also 'disappears' (e.g. file reshuffled).
    lucky = _finding("eslint", "x", "src/Widget.tsx", 999)
    corr2 = szz.correspond([lucky], [], REACT_PATCH, lucky, window=2)
    _expect(corr2.detected_before and corr2.gone_after, "before/after set")
    _expect(not corr2.causal, "not on fixed lines")
    _expect(not corr2.confirmed_catch, "gone-but-not-causal is NOT a confirmed catch")


RENAME_PATCH = """diff --git a/src/Old.tsx b/src/New.tsx
rename from src/Old.tsx
rename to src/New.tsx
--- a/src/Old.tsx
+++ b/src/New.tsx
@@ -10,3 +10,4 @@ export function Widget() {
     window.addEventListener('resize', onResize);
-  }, []);
+  }, []);  // touched, but the leak is NOT actually fixed
+  // (rule still fires on the new path below)
 }
"""


def test_correspondence_rename_not_confirmed():
    # fix renames Old.tsx -> New.tsx and edits the line, but the SAME rule still fires on
    # the renamed file. That is a file-move, not a fix: it must NOT count as confirmed.
    before = [_finding("ownaudit", "OWN-EFFECT", "src/Old.tsx", 11)]
    after = [_finding("ownaudit", "OWN-EFFECT", "src/New.tsx", 11)]  # persists under new path
    corr = szz.correspond(before, after, RENAME_PATCH, before[0], window=2)
    _expect(corr.detected_before, "flagged before")
    _expect(not corr.gone_after, "rule still fires on the renamed path -> not gone")
    _expect(not corr.confirmed_catch, "rename+persisting finding is NOT a confirmed catch")


# ---- lead-time over a real temp git repo -----------------------------------------

def _git(repo, *args, date="2024-01-01T00:00:00"):
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", "-C", repo, *args], env=env,
                          capture_output=True, text=True, check=True)


def test_lead_time():
    with tempfile.TemporaryDirectory() as repo:
        _git(repo, "init", "-q", "-b", "main")
        path = os.path.join(repo, "svc.cs")
        # commit 1: introduce a leaking line.
        with open(path, "w") as fh:
            fh.write("class S {\n  void M() { Tick += OnTick; }\n}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "intro", date="2024-01-01T00:00:00")
        leak_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        # a couple of unrelated commits.
        for i, d in enumerate(("2024-02-01T00:00:00", "2024-03-01T00:00:00")):
            with open(os.path.join(repo, f"f{i}.txt"), "w") as fh:
                fh.write("x\n")
            _git(repo, "add", "."); _git(repo, "commit", "-qm", f"noise{i}", date=d)
        # the human fix: change line 2.
        with open(path, "w") as fh:
            fh.write("class S {\n  void M() { Tick += OnTick; Unloaded += () => Tick -= OnTick; }\n}\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "fix leak", date="2024-04-01T00:00:00")

        lt = szz.lead_time(repo, leak_sha, "svc.cs", 2)
        _expect(lt.found, "fix located in history")
        # 2 intervening commits (noise0, noise1); the fix commit itself is excluded.
        _expect(lt.commits_between == 2, f"2 intervening commits, got {lt.commits_between}")
        _expect(lt.fix_date.startswith("2024-04-01"), f"fix date {lt.fix_date}")


# ---- confirm (verdict combiner) --------------------------------------------------

def test_judge_unique_catch_and_miss():
    own_before = [_finding("ownaudit", "OWN-EFFECT", "src/Widget.tsx", 13, resolution="interproc")]
    cand = confirm.Candidate(
        id="c1", ecosystem="react_ts", title="fix memory leak", body="listener leak",
        patch=REACT_PATCH,
        before={"ownaudit": own_before, "eslint": []},
        after={"ownaudit": [], "eslint": []},
    )
    v = confirm.judge(cand, ownaudit_tool="ownaudit", baseline_tools=("eslint",))
    _expect(v.is_real_fix, "real fix")
    _expect("ownaudit" in v.caught_by, "ownaudit caught")
    _expect(v.unique_to_ownaudit, "unique to ownaudit (eslint missed)")
    _expect("eslint" in v.missed_by, "eslint in missed_by")
    _expect(v.own_resolution == "interproc", f"resolution {v.own_resolution}")


def test_judge_tool_catch_does_not_define_real_fix():
    # a borderline patch (candidate but score < 10) that a tool confirm-catches must NOT be
    # promoted to a "real fix" — ground truth is the patch signal, not the tool's catch.
    patch = ("diff --git a/a.tsx b/a.tsx\n--- a/a.tsx\n+++ b/a.tsx\n"
             "@@ -1,3 +1,3 @@\n function setup() {\n-  window.addEventListener('x', f);\n"
             "+  window.removeEventListener('x', f);\n }\n")
    cand = confirm.Candidate(
        id="b1", ecosystem="react_ts", title="improve effect cleanup", body="", patch=patch,
        before={"ownaudit": [_finding("ownaudit", "OWN-X", "a.tsx", 2)]},
        after={"ownaudit": []},
    )
    v = confirm.judge(cand, ownaudit_tool="ownaudit")
    _expect("ownaudit" in v.caught_by, "catch still recorded")
    _expect(not v.is_real_fix, "tool catch must not define a real fix")
    _expect("borderline-send-to-review" in v.notes, "routed to review instead")


def test_fp_after_matches_rule_and_file():
    patch = ("diff --git a/a.cs b/a.cs\n--- a/a.cs\n+++ b/a.cs\n"
             "@@ -5,2 +5,3 @@\n void M() {\n+  DoThing();\n }\n")
    # same (rule, file) survives on a touched file -> precision smell.
    same = confirm.Candidate(
        id="f1", ecosystem="dotnet_wpf", title="t", body="", patch=patch,
        before={"ownaudit": [_finding("ownaudit", "R1", "a.cs", 5)]},
        after={"ownaudit": [_finding("ownaudit", "R1", "a.cs", 5)]},
    )
    _expect(confirm._fp_after(same, "ownaudit"), "surviving same rule+file is a smell")
    # a DIFFERENT rule on the same file must not count.
    diff = confirm.Candidate(
        id="f2", ecosystem="dotnet_wpf", title="t", body="", patch=patch,
        before={"ownaudit": [_finding("ownaudit", "R1", "a.cs", 5)]},
        after={"ownaudit": [_finding("ownaudit", "R2", "a.cs", 9)]},
    )
    _expect(not confirm._fp_after(diff, "ownaudit"), "unrelated rule must not inflate fp_after")


def test_judge_unique_miss():
    # a real fix (strong patch signal) that NO tool caught -> the precious blind-spot bucket.
    cand = confirm.Candidate(
        id="c2", ecosystem="react_ts", title="fix memory leak", body="listener leak",
        patch=REACT_PATCH, before={"ownaudit": [], "eslint": []}, after={"ownaudit": [], "eslint": []},
    )
    v = confirm.judge(cand, ownaudit_tool="ownaudit", baseline_tools=("eslint",))
    _expect(v.is_real_fix, "still a real fix by patch signal")
    _expect(not v.caught_by, "no tool caught it")
    _expect("real-fix-no-tool-caught" in v.notes, "flagged as shared blind spot")


# ---- metrics ---------------------------------------------------------------------

def test_metrics_aggregate():
    vs = [
        confirm.Verdict("a", "react_ts", "subscription-leak", 12, True,
                        caught_by=["ownaudit"], missed_by=["eslint"], unique_to_ownaudit=True,
                        own_resolution="interproc"),
        confirm.Verdict("b", "react_ts", "timer-leak", 11, True,
                        caught_by=["ownaudit", "eslint"], unique_to_ownaudit=False,
                        own_resolution="syntactic"),
        confirm.Verdict("c", "react_ts", "subscription-leak", 9, True, caught_by=[],
                        missed_by=["ownaudit", "eslint"], notes=["real-fix-no-tool-caught"]),
    ]
    rep = metrics.aggregate(vs, ownaudit_tool="ownaudit", baseline_tools=("eslint",))
    _expect(rep.n_real_fixes == 3, "3 real fixes")
    _expect(rep.catches["ownaudit"] == 2, "ownaudit caught 2")
    _expect(rep.unique_to_ownaudit == 1, "1 unique to ownaudit")
    _expect(rep.unique_miss == 1, "1 shared blind spot")
    _expect(abs(rep.recall_on_corpus["ownaudit"] - 2 / 3) < 1e-3, "ownaudit recall 2/3")
    _expect(rep.by_tier.get("interproc") == 1 and rep.by_tier.get("syntactic") == 1, "tier split")
    md = metrics.render_markdown(rep)
    _expect("LeakFixMine" in md and "by analysis tier" in md, "markdown renders")


# ---- sweep (over-vetted selection) -----------------------------------------------

def test_sweep_over_vetted():
    polished = sweep.Package("Serilog", "nuget", downloads=10**8, stars=6000, maintainers=8,
                             open_issues=10, age_days=3000, has_ci=True, shape="library")
    appish = sweep.Package("acme-dashboard", "npm", downloads=10**6, stars=400, maintainers=2,
                           open_issues=120, age_days=400, has_ci=False, shape="application")
    sp = sweep.over_vetted_score(polished)
    sa = sweep.over_vetted_score(appish)
    _expect(sp.vetted > sa.vetted, "polished lib scores more vetted")
    _expect("high-stars-per-issue" in sp.reason, "stars/issue signal fires")

    # many polished libs + a few apps; cap must let apps through despite higher downloads.
    pkgs = [sweep.Package(f"lib{i}", "nuget", downloads=10**8, stars=8000, maintainers=9,
                          open_issues=5, age_days=3000, has_ci=True, shape="library")
            for i in range(8)]
    pkgs += [appish, sweep.Package("ctrl-plane", "npm", downloads=5 * 10**5, stars=200,
                                   open_issues=90, age_days=300, shape="application")]
    chosen = sweep.select_targets(pkgs, n=5, max_vetted_fraction=0.4)
    names = {c.pkg.name for c in chosen}
    n_vetted = sum(1 for c in chosen if c.vetted >= 0.6)
    _expect(n_vetted <= 2, f"vetted cap (<=40% of 5) respected, got {n_vetted}")
    _expect(names & {"acme-dashboard", "ctrl-plane"}, "an app-shaped repo got in")


def test_sweep_underfill_is_intentional():
    # an all-vetted pool can't fill n without breaching the cap: underfill is intentional,
    # NOT a backfill with the very libs the cap excludes.
    pkgs = [sweep.Package(f"lib{i}", "nuget", downloads=10**8, stars=8000, maintainers=9,
                          open_issues=5, age_days=3000, has_ci=True, shape="library")
            for i in range(10)]
    chosen = sweep.select_targets(pkgs, n=5, max_vetted_fraction=0.4)
    _expect(len(chosen) == 2, f"hard cap -> 2 of 5 (intentional underfill), got {len(chosen)}")
    _expect(all(c.vetted >= 0.6 for c in chosen), "the two admitted are the vetted libs")


# ---- collect (deterministic query/SQL gen) ---------------------------------------

def test_queries_and_sql():
    qs = collect.github_search_queries("react_ts", merged_after="2023-01-01")
    _expect(all("merged:>=2023-01-01" in q for q in qs), "date qualifier appended")
    _expect(any("useEffect" in q for q in qs), "useEffect query present")

    sql = collect.gharchive_sql("dotnet_wpf", date_from="20240101", date_to="20241231")
    _expect("_TABLE_SUFFIX BETWEEN '20240101' AND '20241231'" in sql, "partition-scoped")
    _expect("PullRequestEvent" in sql and "memory leak" in sql, "PR + keyword filter")
    _expect("pull_request.title" in sql and "pull_request.body" in sql, "title AND body matched")


def test_fetch_search_with_fake_http():
    fake = json.dumps({"items": [
        {"number": 7, "title": "fix leak", "html_url": "https://x/pr/7",
         "repository_url": "https://api.github.com/repos/acme/widget", "pull_request": {}},
    ]}).encode()
    got = collect.fetch_search("q", http=lambda url, token: fake)
    _expect(len(got) == 1 and got[0].kind == "pr", "parsed one PR")
    _expect(got[0].repo == "acme/widget", f"repo parsed: {got[0].repo}")


def test_fetch_patch_with_fake_http():
    calls = {}
    def fake_http(url, token):
        calls["url"] = url
        calls["token"] = token
        return "diff --git a/a b/a\n@@ -1 +1 @@\n-x\n+y\n"
    out = collect.fetch_patch("acme/w", 7, token="T", http=fake_http)
    _expect(out.startswith("diff --git"), "returns diff text")
    _expect(calls["url"].endswith("/repos/acme/w/pulls/7"), f"url {calls['url']}")
    _expect(calls["token"] == "T", "token threaded through")
    # a fetch error must degrade to "" (one bad PR can't abort a mining run), not raise.
    def boom(url, token):
        raise RuntimeError("network")
    _expect(collect.fetch_patch("a/b", 1, http=boom) == "", "fetch error -> empty string")


def test_mine_run_orchestration():
    cands = [
        collect.Candidate("", "acme/w", 1, "pr", "fix memory leak", "u1", "listener leak"),
        collect.Candidate("", "acme/w", 1, "pr", "dup of #1", "u1", ""),     # dedup by (repo,#)
        collect.Candidate("", "acme/x", 2, "pr", "chore: tidy", "u2", ""),   # weak -> dropped
        collect.Candidate("", "acme/y", 3, "issue", "an issue", "u3", ""),   # not a PR -> skip
    ]
    weak = ("diff --git a/x.tsx b/x.tsx\n--- a/x.tsx\n+++ b/x.tsx\n"
            "@@ -1,1 +1,1 @@\n-const a = 1;\n+const a = 2;\n")
    patches = {("acme/w", 1): REACT_PATCH, ("acme/x", 2): weak}

    def fake_search(query, *, token="", per_page=50):
        return cands  # query pack repeats the same hits; dedup must collapse them

    def fake_patch(repo, number, *, token=""):
        return patches.get((repo, number), "")

    conn = schema.connect(":memory:")
    res = mine.run("react_ts", search=fake_search, fetch_patch=fake_patch, conn=conn, min_score=7)
    _expect(res.seen == 2, f"PR-only + deduped examined, got {res.seen}")
    _expect(res.kept == 1, f"only the real leak fix kept, got {res.kept}")
    _expect(res.rows and res.rows[0]["repo"] == "acme/w", "kept the leak fix")
    _expect(res.rows[0]["category"] == signals.SUBSCRIPTION, "classified as subscription")
    _expect(schema.count(conn, "candidates") == 1, "kept candidate stored")
    _expect(schema.count(conn, "labels") == 1, "kept label stored")
    _expect("mining run" in res.summary_md(), "summary renders")


# ---- schema (store round-trip) ---------------------------------------------------

def test_schema_store():
    conn = schema.connect(":memory:")
    schema.insert_candidate(conn, {"id": "c1", "ecosystem": "react_ts", "repo": "a/b",
                                   "number": 1, "kind": "pr", "title": "fix leak", "merged": 1})
    schema.insert_label(conn, "c1", "subscription-leak", 12, ["patch:subscription-leak"], "patch")
    v = confirm.Verdict("c1", "react_ts", "subscription-leak", 12, True,
                        caught_by=["ownaudit"], unique_to_ownaudit=True)
    schema.insert_verdict(conn, v)
    _expect(schema.count(conn, "candidates") == 1, "candidate stored")
    _expect(schema.count(conn, "labels") == 1, "label stored")
    _expect(schema.count(conn, "verdicts") == 1, "verdict stored")


def test_candidate_upsert_preserves_children():
    # re-inserting a candidate must UPDATE in place, not DELETE+reinsert — otherwise (with
    # FK on) it would orphan/cascade the child label below.
    conn = schema.connect(":memory:")
    schema.insert_candidate(conn, {"id": "c1", "ecosystem": "react_ts", "title": "old", "merged": 1})
    schema.insert_label(conn, "c1", "subscription-leak", 12, ["e"], "patch")
    schema.insert_candidate(conn, {"id": "c1", "ecosystem": "react_ts", "title": "new", "merged": 1})
    _expect(schema.count(conn, "candidates") == 1, "still one candidate")
    _expect(schema.count(conn, "labels") == 1, "child label survived the re-insert")
    title = conn.execute("SELECT title FROM candidates WHERE id='c1'").fetchone()[0]
    _expect(title == "new", f"row updated in place, title={title}")


def test_schema_verdict_idempotent():
    # re-confirming the same candidate upserts, so resume never double-counts verdicts.
    conn = schema.connect(":memory:")
    schema.insert_candidate(conn, {"id": "c1", "ecosystem": "react_ts", "title": "t", "merged": 1})
    v = confirm.Verdict("c1", "react_ts", "subscription-leak", 12, True, caught_by=["ownaudit"])
    schema.insert_verdict(conn, v)
    schema.insert_verdict(conn, v)  # second confirm of the same candidate
    _expect(schema.count(conn, "verdicts") == 1, "verdict upserts, not duplicated")


def test_schema_foreign_keys_enforced():
    # FK enforcement is ON: a verdict for an unknown candidate must be rejected.
    conn = schema.connect(":memory:")
    v = confirm.Verdict("ghost", "react_ts", "subscription-leak", 12, True)
    try:
        schema.insert_verdict(conn, v)
        raised = False
    except sqlite3.IntegrityError:           # specifically the FK rejection, not any error
        raised = True
    _expect(raised, "orphan verdict rejected by foreign-key constraint")


def test_bq_gharchive_sql():
    sql = bigquery.gharchive_discovery_sql("dotnet_wpf", date_from="20240101", date_to="20241231",
                                          max_changed_files=80)
    _expect("_TABLE_SUFFIX BETWEEN '20240101' AND '20241231'" in sql, "partition-scoped")
    # assert the actual OR boolean, not mere field presence (an AND regression must fail).
    _expect(("title')) LIKE '%memory leak%' OR "
             "LOWER(COALESCE(JSON_EXTRACT_SCALAR(payload,'$.pull_request.body'),'')) "
             "LIKE '%memory leak%'") in sql, "title OR body, not AND")
    _expect("base.repo.language')) = 'c#'" in sql, "language filter")
    _expect("changed_files') AS INT64) <= 80" in sql, "size cap applied")
    _expect("QUALIFY ROW_NUMBER()" in sql, "deduped to one row per PR")
    # size cap can be disabled.
    nocap = bigquery.gharchive_discovery_sql("react_ts", date_from="20240101", date_to="20240131",
                                            max_changed_files=0)
    _expect("changed_files') AS INT64) <=" not in nocap, "cap omitted when 0")


def test_bq_contents_sweep_sql():
    s = bigquery.contents_sweep_sql("react_ts", sample=True)
    _expect("sample_files" in s and "sample_contents" in s, "uses cheap sample tables by default")
    _expect("REGEXP_CONTAINS(c.content, r'addEventListener\\(')" in s, "acquire regex present")
    _expect("NOT REGEXP_CONTAINS(c.content, r'removeEventListener')" in s, "cleanup-absence test")
    full = bigquery.contents_sweep_sql("react_ts", sample=False)
    _expect("github_repos.files`" in full and "github_repos.contents`" in full, "full tables")
    _expect("2.7TB" in full, "full scan is cost-warned")
    # an ecosystem without sweep pairs raises rather than emit garbage.
    raised = False
    try:
        bigquery.contents_sweep_sql("nim")
    except ValueError:
        raised = True
    _expect(raised, "missing sweep pairs -> explicit error")


def test_bq_metadata_score():
    hi, ev = bigquery.metadata_score("dotnet_wpf", title="Fix memory leak in view",
                                    body="event handler retained", changed_files=4)
    _expect(hi >= 4 and "small-pr" in ev, f"focused leak fix ranks high, {hi}")
    lo, ev2 = bigquery.metadata_score("dotnet_wpf", title="Fix memory leak", body="",
                                     changed_files=500)
    # +3 title keyword, -3 mega penalty -> 0; assert the score, not just the evidence.
    _expect(lo == 0 and "penalty:mega-pr" in ev2, f"mega-PR penalty zeroes the score, {lo}")
    none, _ = bigquery.metadata_score("dotnet_wpf", title="add feature", body="", changed_files=3)
    _expect(none < 4, "no-keyword PR below threshold")


def test_bq_ingest_ndjson():
    ndjson = "\n".join([
        json.dumps({"repo": "a/b", "number": 1, "title": "Fix memory leak", "body": "x",
                    "changed_files": 3, "html_url": "u1"}),
        json.dumps({"repo": "a/b", "number": 1, "title": "dup", "body": "", "changed_files": 3}),
        json.dumps({"repo": "c/d", "number": 9, "title": "add feature", "body": "",
                    "changed_files": 2}),  # no keyword -> dropped
    ])
    rows = bigquery.read_ndjson(ndjson)
    conn = schema.connect(":memory:")
    res = bigquery.ingest_rows(rows, "dotnet_wpf", min_meta_score=4, conn=conn)
    _expect(res.seen == 2, f"deduped by (repo,number), got {res.seen}")
    _expect(res.kept == 1, f"only the keyword'd small PR kept, got {res.kept}")
    _expect(res.rows[0]["repo"] == "a/b", "kept the leak PR")
    _expect(schema.count(conn, "candidates") == 1 and schema.count(conn, "labels") == 1, "stored")
    _expect("metadata tier" in res.summary_md(), "summary flags the tier")


def test_signals_no_oom_substring_noise():
    # bare "oom" was removed (it matched zoom/room/doom under substring) — junk titles must
    # not register a leak keyword, but a real leak title still must.
    for junk in ("Refactor Room screen", "bump react-zoom-pan-pinch", "New Gloomier Bangs"):
        cls = signals.classify("react_ts", title=junk, body="", patch="")
        _expect("title:leak-keyword" not in cls.evidence, f"{junk!r} must not match a keyword")
    cls = signals.classify("react_ts", title="fix memory leak", body="", patch="")
    _expect("title:leak-keyword" in cls.evidence, "real leak title still matches")


def test_classify_from_store():
    conn = schema.connect(":memory:")
    schema.insert_candidate(conn, {"id": "a/b#1", "ecosystem": "react_ts", "repo": "a/b",
                                   "number": 1, "kind": "pr", "title": "fix memory leak",
                                   "body": "listener leak", "merged": 1})
    schema.insert_candidate(conn, {"id": "c/d#2", "ecosystem": "react_ts", "repo": "c/d",
                                   "number": 2, "kind": "pr", "title": "chore: tidy",
                                   "body": "", "merged": 1})
    patches = {("a/b", 1): REACT_PATCH,
               ("c/d", 2): "diff --git a/x.tsx b/x.tsx\n--- a/x.tsx\n+++ b/x.tsx\n"
                           "@@ -1,1 +1,1 @@\n-const a = 1;\n+const a = 2;\n"}

    def fake_patch(repo, number, *, token=""):
        return patches.get((repo, number), "")

    res = mine.classify_from_store(conn, "react_ts", fetch_patch=fake_patch, min_score=7)
    _expect(res.seen == 2, f"both stored PRs examined, {res.seen}")
    _expect(res.fetched == 2, f"both diffs fetched, {res.fetched}")
    _expect(res.kept == 1, f"only the real leak fix kept at patch tier, {res.kept}")
    _expect(res.rows[0]["repo"] == "a/b" and res.rows[0]["category"] == signals.SUBSCRIPTION,
            "patch-tier category assigned")
    n = conn.execute("SELECT COUNT(*) FROM labels WHERE classifier='patch'").fetchone()[0]
    _expect(n == 1, f"one patch-tier label written to the store, {n}")


def test_bq_ingest_rejects_contents_rows():
    # contents-sweep rows (repo/path/signal, no PR number) must fail fast, not silently drop.
    rows = [{"repo": "a/b", "path": "src/x.tsx", "signal": "listener"}]
    raised = False
    try:
        bigquery.ingest_rows(rows, "react_ts")
    except ValueError:
        raised = True
    _expect(raised, "contents-sweep rows rejected by bq-ingest")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok - {len(tests)} leakmine tests passed")


if __name__ == "__main__":
    main()
