#!/usr/bin/env python3
"""The corpus runner: base SHA vs head SHA over one corpus, through one CLI.

    PYTHONPATH=. python3 -m corpusdiff.run_differential \\
        --repo /path/to/Own.NET --base main --head HEAD --merge-base \\
        --corpus corpus/mini \\
        --out artifacts/mini-diff \\
        --expect corpusdiff/expectations/own-check-start-column.json

It checks the two commits out into their own git worktrees, runs `own-check` in
each over the SAME corpus paths, normalizes both SARIF logs, and hands the two
payloads to `corpusdiff.diff`. It writes every intermediate it used, so the
verdict is re-derivable from the artifacts alone.

WHY WORKTREES AND NOT TWO CHECKOUTS
-----------------------------------
Two checkouts of one repository share nothing and drift independently; two
worktrees share the object store, so "the base side" is provably the same
repository's commit and not a stale clone that happens to have a similar name.
They are also cheap enough to make per-run isolation the default instead of a
thing you remember to do.

WHY THE BASELINE IS A COMMIT AND NOT ONLY A GOLDEN FILE
------------------------------------------------------
A committed golden is a claim about what the output was when somebody last
remembered to regenerate it. A merge-base checkout is a claim about what the
output IS on the branch this change will land on. The second catches a regression
against real main even when the golden is stale - which is precisely the state a
golden is usually in. Golden files keep their place for the fixture-level
contract tests, where the point is to pin an exact shape; they are not the only
source of truth about a corpus.

WHY IT SHELLS OUT TO `own-check.sh`
-----------------------------------
Because that is the boundary. OwnAudit consumes Own.NET through its CLI and its
SARIF, never by importing its Python; a runner that reached into `ownlang` would
re-create the coupling the two repos were split to remove, and would then be
testing a hybrid neither repository ships.

PATHS ARE STRIPPED, OR NOTHING IS COMPARABLE
--------------------------------------------
Each side runs inside its own worktree, so its findings are reported under that
worktree's absolute path. Unstripped, EVERY finding would look like it moved file
and the report would be a wall of new/removed patterns. The worktree prefix is
passed to the normalizer as `--strip`, which is what makes the two sides describe
the same corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregate.normalize import build_payload, load_taxonomy                     # noqa: E402
from corpusdiff.delta import STRICT, DeltaError, load as load_expectation        # noqa: E402
from corpusdiff.diff import compare, render_markdown                             # noqa: E402
from corpusdiff.project import ProjectionError                                   # noqa: E402

#: The producer name both sides are normalized under. It is the same tool on both
#: sides by construction, and the anchor projection keys on it - two different
#: names would make every site look like it belonged to a different producer.
PRODUCER = "own-check"

#: The runner's own record of what it did. Written next to the report so the
#: evidence travels with the verdict.
RUN_SCHEMA = "corpus-differential-run/v1"


class RunnerError(RuntimeError):
    """The run could not be completed. Never downgraded to an empty diff."""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RunnerError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def corpus_digest(root: Path, paths: list[str]) -> dict[str, Any]:
    """A digest over the corpus INPUTS, not over the findings.

    Two runs that disagree are only evidence about the producer if they read the
    same bytes. This is the field that makes "the corpus was identical" a checkable
    claim rather than an assumption - and it is computed from the head worktree,
    because the corpus is versioned with the code and a corpus change is itself a
    reason for the outputs to differ.
    """
    files: list[tuple[str, str]] = []
    for rel in paths:
        target = root / rel
        if target.is_file():
            files.append((rel, _sha256_file(target)))
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file():
                files.append((str(path.relative_to(root)).replace(os.sep, "/"),
                              _sha256_file(path)))
    files.sort()
    roll = hashlib.sha256()
    for rel, digest in files:
        roll.update(rel.encode("utf-8"))
        roll.update(b"\0")
        roll.update(digest.encode("utf-8"))
        roll.update(b"\0")
    return {"files": len(files), "digest": f"sha256:{roll.hexdigest()}",
            "entries": dict(files)}


def _run_own_check(worktree: Path, corpus: list[str], sarif_out: Path,
                   extra: list[str]) -> None:
    """One producer run, through the CLI, into a SARIF file.

    Exit 1 means "analysed, and there are findings" - the normal outcome for a
    leak corpus, and not an error. Exit >= 2 is the hard-error tier (a broken
    build, refused input, a drifted fact contract) and aborts the run: a corpus
    diff against a side that never produced a verdict would compare a real run
    against an empty file and report the whole corpus as removed.
    """
    script = worktree / "scripts" / "own-check.sh"
    if not script.is_file():
        raise RunnerError(f"{script} not found - is --repo an Own.NET checkout?")
    cmd = [str(script), "--root", str(worktree), "--format", "sarif", *extra,
           "--", *corpus]
    with open(sarif_out, "w", encoding="utf-8") as out:
        proc = subprocess.run(cmd, cwd=str(worktree), stdout=out, text=True)
    if proc.returncode >= 2:
        raise RunnerError(
            f"own-check exited {proc.returncode} in {worktree} - that is the "
            f"hard-error tier (no verdict was produced), not a findings result. "
            f"Refusing to diff against a run that did not happen.")
    if sarif_out.stat().st_size == 0:
        raise RunnerError(f"own-check wrote no SARIF to {sarif_out}")


def _write_manifest(path: Path, run_id: str, sarif: Path, commit: str) -> None:
    """A `producer-provenance/v1` manifest for one side.

    The run id is minted HERE, before the diff, and it names the analysis: one id
    per side per run. That is what makes the two sides' occurrence ids legitimately
    different - and why they are never compared to each other.
    """
    path.write_text(json.dumps({
        "schema_version": "producer-provenance/v1",
        "_doc": ["Written by corpusdiff.run_differential, one entry per side.",
                 "The run id names the analysis, not the normalization."],
        "inputs": {PRODUCER: {
            "producer_run_id": run_id,
            "producer_name": PRODUCER,
            "producer_version": None,
            "input_digest": _sha256_file(sarif),
            "config_digest": None,
            "source_commit": commit,
        }},
    }, indent=2), encoding="utf-8")


def _side(repo: Path, out: Path, label: str, commit: str, corpus: list[str],
          run_label: str, extra: list[str], keep: bool,
          digest_corpus: bool = False) -> tuple[dict[str, Any], Path]:
    """Run one side end to end and return `(record, normalized payload path)`.

    `digest_corpus` computes the input digest from THIS side's worktree, while it
    still exists. Doing it afterwards from `--repo` would digest whatever the
    caller's checkout happens to be sitting on, which is usually neither commit.
    """
    worktree = out / label
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    _git(repo, "worktree", "add", "--detach", str(worktree), commit)
    try:
        sarif = out / f"{label}.sarif"
        _run_own_check(worktree, corpus, sarif, extra)
        manifest = out / f"{label}-provenance.json"
        _write_manifest(manifest, f"{run_label}/{label}/{PRODUCER}", sarif, commit)
        payload = build_payload([(PRODUCER, str(sarif))], load_taxonomy(),
                                # Both spellings of the worktree root: `own-check`
                                # may report either, depending on how the path
                                # reached the extractor.
                                [str(worktree), str(worktree.resolve())],
                                str(manifest))
        payload_path = out / f"{label}-normalized.json"
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        record = {
            "label": label,
            "commit": commit,
            "sarif": sarif.name,
            "sarif_digest": _sha256_file(sarif),
            "normalized": payload_path.name,
            "provenance": manifest.name,
            "producer_run_id": f"{run_label}/{label}/{PRODUCER}",
            "findings": len(payload["findings"]),
        }
        if digest_corpus:
            record["corpus"] = corpus_digest(worktree, corpus)
        return record, payload_path
    finally:
        if not keep:
            shutil.rmtree(worktree, ignore_errors=True)
            # `worktree remove` would refuse a directory already gone; prune is the
            # idempotent form and leaves the repository's metadata clean either way.
            try:
                _git(repo, "worktree", "prune")
            except RunnerError:
                pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="corpusdiff.run_differential",
        description="Run own-check at two commits over one corpus and diff the "
                    "normalized results.")
    ap.add_argument("--repo", required=True, help="an Own.NET checkout (a git repo)")
    ap.add_argument("--base", required=True, help="the baseline committish")
    ap.add_argument("--head", required=True, help="the candidate committish")
    ap.add_argument("--merge-base", action="store_true",
                    help="use merge-base(base, head) as the baseline - the state "
                         "the change will actually land on, rather than the tip of "
                         "a branch that has moved on since")
    ap.add_argument("--corpus", action="append", default=[], metavar="PATH",
                    help="repo-relative corpus path (repeatable)")
    ap.add_argument("--out", required=True, help="artifact directory (created)")
    ap.add_argument("--expect", default=None, metavar="FILE",
                    help="a corpus-delta/v1 expectation; without one, no output "
                         "change is signed off")
    ap.add_argument("--own-check-arg", action="append", default=[], metavar="ARG",
                    help="extra argument forwarded to own-check.sh (repeatable)")
    ap.add_argument("--run-label", default="corpusdiff",
                    help="prefix for the two producer run ids")
    ap.add_argument("--keep-worktrees", action="store_true",
                    help="leave the two worktrees in place for inspection")
    ap.add_argument("--no-gate", action="store_true",
                    help="report but do not fail the process")
    args = ap.parse_args(argv)

    if not args.corpus:
        ap.error("--corpus is required (at least one repo-relative path)")

    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    try:
        expect = load_expectation(args.expect) if args.expect else STRICT
    except DeltaError as e:
        print(f"run_differential: {e}", file=sys.stderr)
        return 2

    try:
        head_sha = _git(repo, "rev-parse", args.head)
        base_sha = _git(repo, "rev-parse", args.base)
        if args.merge_base:
            base_sha = _git(repo, "merge-base", base_sha, head_sha)
        if base_sha == head_sha:
            # Not an error, but worth saying plainly: the two sides are one commit,
            # so a PASS here is evidence about nothing.
            print("run_differential: base and head are the SAME commit; the diff "
                  "will be empty and proves nothing about the change",
                  file=sys.stderr)

        # Head first, and it carries the corpus digest: the corpus is versioned
        # with the code, so "which bytes were analysed" is a property of the commit
        # under test, and it must be read while that worktree still exists.
        head_rec, head_payload = _side(repo, out, "head", head_sha, args.corpus,
                                       args.run_label, args.own_check_arg,
                                       args.keep_worktrees, digest_corpus=True)
        base_rec, base_payload = _side(repo, out, "base", base_sha, args.corpus,
                                       args.run_label, args.own_check_arg,
                                       args.keep_worktrees)
    except RunnerError as e:
        print(f"run_differential: {e}", file=sys.stderr)
        return 2

    try:
        report = compare(json.loads(base_payload.read_text(encoding="utf-8")),
                         json.loads(head_payload.read_text(encoding="utf-8")),
                         expect)
    except ProjectionError as e:
        print(f"run_differential: {e}", file=sys.stderr)
        return 2

    run_record = {
        "schema_version": RUN_SCHEMA,
        "repo": str(repo),
        "base": base_rec,
        "head": head_rec,
        "merge_base_used": bool(args.merge_base),
        "corpus_paths": list(args.corpus),
        "corpus": head_rec["corpus"],
        "expectation": args.expect,
        "own_check_args": list(args.own_check_arg),
        "verdict": report["verdict"],
        "gated": not args.no_gate,
    }
    (out / "run.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (out / "report.md").write_text(
        f"<!-- base {base_sha} head {head_sha} corpus "
        f"{run_record['corpus']['digest']} -->\n{markdown}", encoding="utf-8")
    print(markdown)
    print(f"run_differential: base {base_sha[:12]} -> head {head_sha[:12]}, "
          f"{run_record['corpus']['files']} corpus files, artifacts in {out}")

    if report["verdict"] == "pass":
        return 0
    if args.no_gate:
        print("run_differential: --no-gate, so the violations above do not fail "
              "this run", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
