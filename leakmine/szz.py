"""Historical fix attribution — the SZZ-style core that separates a real leak fix from luck.

Two failure modes kill a fixed-bug corpus if you don't guard against them:
  1. A baseline tool's finding "disappears after the fix" for the WRONG reason — the file
     was moved, renamed, or mass-reformatted, not because the leak was closed.
  2. A PR labelled "fix memory leak" actually fixes something else and the leak survives.

The defence is the SZZ intersection test (Śliwerski–Zimmermann–Zeller, 2005, *When do
changes induce fixes?*): a finding anchored at OLD-file `(path, line)` is causally tied to
the fix ONLY if the fix diff deletes or replaces that line. We map findings onto the fix's
removed-line ranges (via `diffparse`), so "gone after" only counts when it is "gone
*because the relevant lines changed*". For heavier needs (rename tracking, refactor vs
behaviour separation) the doc points at PyDriller + RefactoringMiner; here we keep it
stdlib + `git`.

This module also powers the *time-travel* experiment: given a leak OwnAudit flags on an
old revision, `lead_time` walks history forward to the commit where humans actually fixed
that line, yielding "OwnAudit would have caught this N commits / D days earlier."
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from . import diffparse


# ---- thin git wrapper ------------------------------------------------------------

class GitError(RuntimeError):
    pass


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def diff_between(repo: str, base: str, head: str, *paths: str) -> str:
    """Unified diff base->head. `git diff` (not `show`) so merge commits work too."""
    args = ["diff", "--unified=3", "--no-color", f"{base}", f"{head}"]
    if paths:
        args += ["--", *paths]
    return _git(repo, *args)


def is_ancestor(repo: str, maybe_ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor", maybe_ancestor, descendant],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


# ---- finding model ---------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """A tool finding, in OwnAudit's canonical shape (report/sarif.py).

    `resolution` is the *analysis tier* that produced it — the build-dependency axis from
    the design discussion: "syntactic" (raw text/AST, zero build, zero references),
    "semantic" (needs symbol resolution / reference assemblies), or "interproc"
    (cross-procedure ownership — OwnAudit's edge). Metrics slice by it so the
    OwnAudit-vs-ESLint comparison stays apples-to-apples within a tier, and so the study
    can report *how much the build problem even matters* (what % of fixes are catchable
    with zero build).
    """
    tool: str
    rule: str
    file: str
    line: int
    category: str = ""
    tier: str = ""          # fix-risk tier (T1..T4), report/sarif.py compatibility
    resolution: str = ""    # analysis tier: syntactic | semantic | interproc

    def key(self) -> tuple[str, str, str, int]:
        return (self.tool, self.rule, self.file, self.line)


@dataclass
class Attribution:
    finding: "Finding"
    fix_touches: bool       # the fix deleted/replaced the finding's line (SZZ test)
    in_changed_file: bool   # the fix touched the file at all
    reason: str


def attribute(patch: str, finding: "Finding", *, window: int = 2) -> Attribution:
    """Does the fix patch causally touch this pre-fix finding?

    `window` tolerates a small off-by-N (the fix adds the missing `-=` a couple of lines
    below the `+=` the finding flagged). Keep it tight — a wide window re-admits the very
    coincidence we're filtering out.
    """
    for fd in diffparse.parse_patch(patch):
        # match on either side's path (the finding is on the OLD side, but renames move it).
        if finding.file not in (fd.old_path, fd.new_path, fd.path):
            continue
        if fd.is_delete:
            return Attribution(finding, False, True, "file-deleted")  # gone, but not a fix
        if fd.touches_old_line(finding.line, window=window):
            return Attribution(finding, True, True, "fix-touches-finding")
        return Attribution(finding, False, True, "file-changed-elsewhere")
    return Attribution(finding, False, False, "file-untouched")


# ---- before/after correspondence -------------------------------------------------

@dataclass
class Correspondence:
    detected_before: bool   # tool flagged it on the pre-fix revision
    gone_after: bool        # the same finding is absent on the post-fix revision
    causal: bool            # gone_after AND the fix actually touched the finding's line

    @property
    def confirmed_catch(self) -> bool:
        """The honest definition: flagged before, gone after, AND gone *because* the fix
        changed the flagged lines — not because the file moved or was reformatted."""
        return self.detected_before and self.gone_after and self.causal


def correspond(
    before: list["Finding"],
    after: list["Finding"],
    patch: str,
    target: "Finding",
    *,
    window: int = 2,
) -> Correspondence:
    """Cross a target finding against before/after tool runs and the fix patch."""
    before_keys = {f.key() for f in before}
    detected = target.key() in before_keys
    # "gone" is matched on (tool, rule, file) since the line number legitimately shifts
    # across the fix; exact-line matching would falsely report every finding as "gone".
    after_loose = {(f.tool, f.rule, f.file) for f in after}
    # A rename moves the after-finding onto the NEW path, so checking only the old path
    # would call a rename "gone" even when the same rule still fires on the renamed file —
    # exactly the file-move case this guard exists to exclude. Follow the rename(s).
    post_paths = {target.file}
    for fd in diffparse.parse_patch(patch):
        if fd.old_path == target.file and fd.new_path not in ("", "/dev/null"):
            post_paths.add(fd.new_path)
    gone = not any((target.tool, target.rule, p) in after_loose for p in post_paths)
    causal = attribute(patch, target, window=window).fix_touches
    return Correspondence(detected_before=detected, gone_after=gone, causal=causal)


# ---- time-travel: lead time ------------------------------------------------------

@dataclass
class LeadTime:
    fix_sha: str
    fix_date: str           # ISO-8601 committer date
    commits_between: int    # intervening commits strictly between leak and fix (both excluded)
    found: bool


def lead_time(repo: str, leak_sha: str, file: str, line: int) -> LeadTime:
    """From a leak OwnAudit flags at `leak_sha:(file,line)`, find the FIRST later commit
    that modified that line — the human fix — and measure the gap.

    Uses `git log -L` to follow the single line through history, then keeps only commits
    that descend from `leak_sha` (so we look forward, not back), and takes the oldest of
    those: that is when humans got around to it.
    """
    try:
        out = _git(
            repo, "log", "--format=%H|%cI", f"-L{line},{line}:{file}", "--no-patch",
        )
    except GitError:
        return LeadTime("", "", -1, False)

    # commits are newest-first; collect (sha, date) pairs.
    commits: list[tuple[str, str]] = []
    for ln in out.splitlines():
        if "|" in ln and len(ln.split("|", 1)[0]) >= 7:
            sha, _, date = ln.partition("|")
            commits.append((sha.strip(), date.strip()))

    # forward fixes = strictly after leak_sha (leak_sha is their ancestor, and != them).
    forward = [
        (sha, date) for sha, date in commits
        if sha != _rev(repo, leak_sha) and is_ancestor(repo, leak_sha, sha)
    ]
    if not forward:
        return LeadTime("", "", -1, False)

    fix_sha, fix_date = forward[-1]  # oldest forward commit = the first human fix
    # `leak..fix` excludes the leak (range start) but INCLUDES the fix (range tip); drop the
    # fix itself so commits_between is the strictly-intervening count, as documented.
    between = max(0, _count_commits(repo, leak_sha, fix_sha) - 1)
    return LeadTime(fix_sha=fix_sha, fix_date=fix_date, commits_between=between, found=True)


def _rev(repo: str, ref: str) -> str:
    return _git(repo, "rev-parse", ref).strip()


def _count_commits(repo: str, base: str, head: str) -> int:
    out = _git(repo, "rev-list", "--count", f"{base}..{head}")
    return int(out.strip() or "0")
