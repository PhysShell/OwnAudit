"""`corpusdiff.run_differential` orchestration tests. Bare python3 or pytest:

    PYTHONUTF8=1 PYTHONPATH=. python3 corpusdiff/tests/test_runner.py

The runner's job is plumbing, and plumbing is where a differential harness fails
silently: a stripped path that was not stripped turns every finding into a moved
file, a producer that crashed turns into an empty baseline, and a leftover
worktree turns the next run into a stale one. None of those show up as a wrong
verdict - they show up as a confident wrong verdict.

So this drives the real runner against a real git repository with a STUB
producer: a `scripts/own-check.sh` that prints a fixed SARIF log at absolute
worktree paths and exits 1, the way a producer with findings does. No .NET is
needed to test the harness, and the harness is what is under test here - the
producer has its own tests in its own repository.

WHAT IS PINNED
--------------
  * base and head really are checked out separately, and the verdict comes from
    the two commits rather than from whatever the caller's checkout was on;
  * the worktree prefix IS stripped, so both sides describe one corpus;
  * `--merge-base` resolves to the fork point, not to the tip of a branch that
    has moved on;
  * a producer in the hard-error tier ABORTS instead of yielding an empty side;
  * the run record carries the SHAs and the input digest, so the verdict is
    re-derivable from the artifacts;
  * the worktrees are gone afterwards unless the caller asked to keep them.

-O-safe (explicit raises, no bare assert). ASCII-only output.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from corpusdiff.run_differential import corpus_digest, main                      # noqa: E402
from pathlib import Path                                                         # noqa: E402

EXPECTATION = os.path.join(ROOT, "corpusdiff", "expectations",
                           "own-check-start-column.json")

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


#: A stub producer. `$PWD` is the worktree the runner ran it in, so the SARIF
#: carries ABSOLUTE paths - exactly the shape that makes stripping load-bearing.
#: Exits 1: "analysed, and there are findings", the normal outcome for a leak
#: corpus and not an error.
STUB = r"""#!/usr/bin/env bash
set -euo pipefail
cat <<JSON
{
  "version": "2.1.0",
  "runs": [{"tool": {"driver": {"name": "Owen"}}, "results": [
    {"ruleId": "OWN001", "level": "warning",
     "message": {"text": "event subscribed but never unsubscribed [resource: subscription token]"},
     "locations": [{"physicalLocation": {
       "artifactLocation": {"uri": "$PWD/corpus/mini/Subscription.cs"},
       "region": {"startLine": 12COLUMN_A}}}]},
    {"ruleId": "OWN001", "level": "warning",
     "message": {"text": "timer never stopped [resource: timer]"},
     "locations": [{"physicalLocation": {
       "artifactLocation": {"uri": "$PWD/corpus/mini/Timer.cs"},
       "region": {"startLine": 30COLUMN_B}}}]}
  ]}]
}
JSON
exit 1
"""

FAILING_STUB = r"""#!/usr/bin/env bash
echo "extractor build failed" >&2
exit 2
"""


def write_stub(repo: str, columns: bool) -> None:
    body = STUB.replace("COLUMN_A", ', "startColumn": 9' if columns else "")
    body = body.replace("COLUMN_B", ', "startColumn": 13' if columns else "")
    path = os.path.join(repo, "scripts", "own-check.sh")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, 0o755)


def build_repo(repo: str) -> tuple[str, str, str]:
    """A repo with a base commit (no columns) and a head commit (columns).

    Returns `(base_sha, head_sha, side_sha)`. `side_sha` is a commit made on the
    base BEFORE head, on its own branch, so `--merge-base` has a fork point that
    is not simply the branch tip to resolve to.
    """
    os.makedirs(os.path.join(repo, "scripts"))
    os.makedirs(os.path.join(repo, "corpus", "mini"))
    for name in ("Subscription.cs", "Timer.cs"):
        with open(os.path.join(repo, "corpus", "mini", name), "w",
                  encoding="utf-8") as fh:
            fh.write(f"// frozen mini-corpus fixture: {name}\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "corpusdiff@example.invalid")
    git(repo, "config", "user.name", "corpusdiff test")
    write_stub(repo, columns=False)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base: producer without columns")
    base = git(repo, "rev-parse", "HEAD")

    # main moves on after the branch forks. A baseline taken from main's TIP would
    # include this commit; the merge base must not.
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("main moved on\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main: unrelated commit after the fork")
    main_tip = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "slice", base)
    write_stub(repo, columns=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head: producer emits startColumn")
    head = git(repo, "rev-parse", "HEAD")
    return base, head, main_tip


def test_pass_and_records(tmp: str) -> None:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    base, head, main_tip = build_repo(repo)
    out = os.path.join(tmp, "out-pass")

    rc = main(["--repo", repo, "--base", "main", "--head", head, "--merge-base",
               "--corpus", "corpus/mini", "--out", out, "--expect", EXPECTATION])
    check(rc == 0, f"the startColumn slice must pass its expectation, rc={rc}")

    report = json.loads(Path(out, "report.json").read_text(encoding="utf-8"))
    check(report["verdict"] == "pass",
          f"report verdict: {report['verdict']} {report.get('violations')}")
    check(report["totals"]["allowed"] == 2 and report["totals"]["violations"] == 0,
          f"expected 2 allowed column transitions: {report['totals']}")

    run = json.loads(Path(out, "run.json").read_text(encoding="utf-8"))
    # --merge-base must resolve to the fork point, NOT to main's tip. Without this
    # the baseline would silently include unrelated commits from main.
    check(run["base"]["commit"] == base,
          f"--merge-base must resolve to the fork point {base[:12]}, got "
          f"{run['base']['commit'][:12]} (main tip is {main_tip[:12]})")
    check(run["head"]["commit"] == head, "the head record must name the head commit")
    check(run["corpus"]["files"] == 2,
          f"the corpus digest must cover both fixtures: {run['corpus']}")
    check(run["corpus"]["digest"].startswith("sha256:"),
          "the corpus digest must be a sha256")
    check(run["base"]["sarif_digest"] != run["head"]["sarif_digest"],
          "the two sides' SARIF digests must differ, or the fixture is not a diff")
    check(run["base"]["producer_run_id"] != run["head"]["producer_run_id"],
          "each side must get its own producer_run_id")

    # Stripping: without it, every finding would look like it moved file, because
    # each side ran under a different worktree path.
    payload = json.loads(Path(out, "head-normalized.json").read_text(encoding="utf-8"))
    paths = sorted(f["path"] for f in payload["findings"])
    check(paths == ["corpus/mini/Subscription.cs", "corpus/mini/Timer.cs"],
          f"the worktree prefix must be stripped from every path: {paths}")

    # Each side minted occurrence ids (a manifest was written), and the two sides
    # share none - the contract this differ is built around.
    base_payload = json.loads(Path(out, "base-normalized.json").read_text(
        encoding="utf-8"))
    ids_b = {f["occurrence_id"] for f in base_payload["findings"]}
    ids_h = {f["occurrence_id"] for f in payload["findings"]}
    check(all(ids_b) and all(ids_h), "both sides must mint occurrence ids")
    check(not (ids_b & ids_h),
          "the two sides must share no occurrence id (producer_run_id is in the hash)")

    check(not os.path.exists(os.path.join(out, "base"))
          and not os.path.exists(os.path.join(out, "head")),
          "the worktrees must be removed unless --keep-worktrees was passed")
    check(git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1,
          "the repository must be left with only its main worktree")


def test_strict_default_fails(tmp: str) -> None:
    """The same run with no expectation must fail: silence is not a signature."""
    repo = os.path.join(tmp, "repo")          # built by test_pass_and_records
    head = git(repo, "rev-parse", "slice")
    out = os.path.join(tmp, "out-strict")
    rc = main(["--repo", repo, "--base", "main", "--head", head, "--merge-base",
               "--corpus", "corpus/mini", "--out", out])
    check(rc == 1, f"an undeclared change must fail with rc=1, got {rc}")
    report = json.loads(Path(out, "report.json").read_text(encoding="utf-8"))
    check(report["verdict"] == "fail", "the report must say fail")

    # --no-gate keeps the evidence and drops only the enforcement. The report must
    # still say `fail`; a softened report would be a different claim.
    out2 = os.path.join(tmp, "out-nogate")
    rc2 = main(["--repo", repo, "--base", "main", "--head", head, "--merge-base",
                "--corpus", "corpus/mini", "--out", out2, "--no-gate"])
    check(rc2 == 0, f"--no-gate must not fail the process, got {rc2}")
    report2 = json.loads(Path(out2, "report.json").read_text(encoding="utf-8"))
    check(report2["verdict"] == "fail",
          "--no-gate must not rewrite the verdict, only the exit code")
    run2 = json.loads(Path(out2, "run.json").read_text(encoding="utf-8"))
    check(run2["gated"] is False, "the run record must say the run was not gated")


def test_producer_hard_error_aborts(tmp: str) -> None:
    """A producer that never produced a verdict must abort the run.

    This is the case that matters most. Exit >= 2 is own-check's hard-error tier
    (a broken build, refused input, a drifted fact contract). Treating it as "no
    findings" would compare a real baseline against an empty candidate and report
    the entire corpus as removed - a spectacular red herring - or, with the
    sides reversed, report a clean pass over nothing at all.
    """
    repo = os.path.join(tmp, "broken")
    os.makedirs(repo)
    base, head, _ = build_repo(repo)
    path = os.path.join(repo, "scripts", "own-check.sh")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(FAILING_STUB)
    os.chmod(path, 0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head: the extractor no longer builds")
    broken = git(repo, "rev-parse", "HEAD")

    out = os.path.join(tmp, "out-broken")
    rc = main(["--repo", repo, "--base", base, "--head", broken,
               "--corpus", "corpus/mini", "--out", out, "--expect", EXPECTATION])
    check(rc == 2, f"a hard-error producer must exit 2 (undecided), got {rc}")
    check(not os.path.exists(os.path.join(out, "report.json")),
          "an aborted run must not leave a report that reads as a verdict")


def test_corpus_digest_sees_content(tmp: str) -> None:
    """The digest must change when the corpus changes, and not otherwise."""
    root = Path(tmp, "digest")
    (root / "mini").mkdir(parents=True)
    (root / "mini" / "A.cs").write_text("one\n", encoding="utf-8")
    first = corpus_digest(root, ["mini"])
    check(first["files"] == 1, f"expected one file: {first}")
    check(corpus_digest(root, ["mini"])["digest"] == first["digest"],
          "the digest must be stable for unchanged bytes")
    (root / "mini" / "A.cs").write_text("two\n", encoding="utf-8")
    check(corpus_digest(root, ["mini"])["digest"] != first["digest"],
          "the digest must change when a corpus file changes")
    (root / "mini" / "B.cs").write_text("one\n", encoding="utf-8")
    check(corpus_digest(root, ["mini"])["files"] == 2,
          "a new corpus file must be counted")
    # A single file, named directly, is a legal corpus path too.
    check(corpus_digest(root, ["mini/A.cs"])["files"] == 1,
          "a file path must be digestible, not only a directory")


def main_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_pass_and_records(tmp)
        test_strict_default_fails(tmp)
        test_producer_hard_error_aborts(tmp)
        test_corpus_digest_sees_content(tmp)
    for f in fails:
        print(f"FAIL: {f}")
    print(f"corpusdiff/tests/test_runner: {'OK' if not fails else 'FAIL'} - 4 cases")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main_test())
