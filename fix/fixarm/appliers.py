"""Applier + re-audit adapters (docs/fix-arm.md §5).

REAL adapters (RoslynatorApplier, DotnetFormatApplier, ScriptReaudit) drive the
off-the-shelf mass appliers and Run-Audit.ps1 — they require .NET / MSBuild and so
run on the Windows stand (the build wall, §6). REPLAY adapters (ReplayApplier,
ReplayReaudit) drive recorded fixtures and run anywhere — that is what CI/Linux and
the tests use. Same wrapper logic over both.
"""
from __future__ import annotations

import difflib
import os
import shutil
import subprocess

from .orchestrate import Finding, findings_from_obj
import json


# ---- replay (CI/Linux, no .NET) --------------------------------------------

def _read(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readlines()
    except FileNotFoundError:
        return []


def _walk(root: str) -> list[str]:
    out = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            full = os.path.join(dirpath, n)
            out.append(os.path.relpath(full, root))
    return sorted(out)


class ReplayApplier:
    """Fixture-driven applier. A fixture dir has before/ and after/ source trees;
    'applying' overlays after/ onto the workdir, and the dry-run diff is computed
    between the two trees with difflib — a real reviewable patch, no .NET needed."""
    name = "replay"

    def __init__(self, fixture_dir: str):
        self.before_dir = os.path.join(fixture_dir, "before")
        self.after_dir = os.path.join(fixture_dir, "after")

    def dry_run(self, workdir: str, rule: str) -> str:
        chunks = []
        for rel in sorted(set(_walk(self.before_dir)) | set(_walk(self.after_dir))):
            a = _read(os.path.join(self.before_dir, rel))
            b = _read(os.path.join(self.after_dir, rel))
            if a != b:
                chunks.extend(difflib.unified_diff(
                    a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return "".join(chunks)

    def apply(self, workdir: str, rule: str) -> None:
        before_files = set(_walk(self.before_dir))
        after_files = set(_walk(self.after_dir))
        # A fix can DELETE a file (present in before/, absent in after/). Overlaying
        # after/ alone would leave it behind and diverge from after.findings.json.
        for rel in before_files - after_files:
            stale = os.path.join(workdir, rel)
            if os.path.exists(stale):
                os.remove(stale)
        for rel in sorted(after_files):
            dst = os.path.join(workdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(self.after_dir, rel), dst)

    def revert(self, workdir: str) -> None:
        """Restore the before/ state — undo apply() on a rejected/ineffective fix.
        Files added by the fix (after-only) are removed; everything else is reset."""
        before_files = set(_walk(self.before_dir))
        after_files = set(_walk(self.after_dir))
        for rel in after_files - before_files:
            stray = os.path.join(workdir, rel)
            if os.path.exists(stray):
                os.remove(stray)
        for rel in sorted(before_files):
            dst = os.path.join(workdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(self.before_dir, rel), dst)


class ReplayReaudit:
    """Returns the fixture's recorded after.findings.json — i.e. what re-running the
    audit over the fixed tree found. The golden regression oracle for the slice."""
    def __init__(self, after_findings_path: str):
        self._path = after_findings_path

    def __call__(self, workdir: str) -> list[Finding]:
        with open(self._path, encoding="utf-8") as fh:
            return findings_from_obj(json.load(fh))


# ---- real adapters (Windows stand, .NET / MSBuild) -------------------------

def _git_revert(workdir: str) -> None:
    """Restore a git-tracked worktree: discard tracked edits and drop new files.
    The real appliers run inside a checkout, so this rolls a rejected fix back out."""
    subprocess.run(["git", "checkout", "--", "."], cwd=workdir, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=workdir, check=True)


class RoslynatorApplier:
    """`roslynator fix` over a solution, filtered to one diagnostic. Loads external
    analyzer assemblies so it can apply INPC/MA/WPF/IDISP fixes too. Dry-run is
    emulated by applying on a throwaway git worktree and diffing (roslynator has no
    native --dry-run). Runs only where dotnet + roslynator are installed."""
    name = "roslynator"

    def __init__(self, solution: str, analyzer_assemblies: list[str] | None = None):
        self.solution = solution
        self.analyzers = analyzer_assemblies or []

    def _cmd(self, rule: str) -> list[str]:
        cmd = ["roslynator", "fix", self.solution, "--supported-diagnostics", rule]
        for asm in self.analyzers:
            cmd += ["--analyzer-assemblies", asm]
        return cmd

    def dry_run(self, workdir: str, rule: str) -> str:
        # Diff a clean checkout against a copy where the fix was applied.
        subprocess.run(self._cmd(rule), cwd=workdir, check=True)
        diff = subprocess.run(["git", "diff"], cwd=workdir, capture_output=True,
                              text=True, check=True).stdout
        subprocess.run(["git", "checkout", "--", "."], cwd=workdir, check=True)
        return diff

    def apply(self, workdir: str, rule: str) -> None:
        subprocess.run(self._cmd(rule), cwd=workdir, check=True)

    def revert(self, workdir: str) -> None:
        _git_revert(workdir)


class DotnetFormatApplier:
    """`dotnet format analyzers` over a project, filtered to one diagnostic.
    Built into the SDK; `--verify-no-changes` gives a cheap dry-run signal."""
    name = "dotnet-format"

    def __init__(self, project: str, severity: str = "info"):
        self.project = project
        self.severity = severity

    def _cmd(self, rule: str, verify: bool = False) -> list[str]:
        cmd = ["dotnet", "format", "analyzers", self.project,
               "--diagnostics", rule, "--severity", self.severity]
        if verify:
            cmd.append("--verify-no-changes")
        return cmd

    def dry_run(self, workdir: str, rule: str) -> str:
        subprocess.run(self._cmd(rule), cwd=workdir, check=True)
        diff = subprocess.run(["git", "diff"], cwd=workdir, capture_output=True,
                              text=True, check=True).stdout
        subprocess.run(["git", "checkout", "--", "."], cwd=workdir, check=True)
        return diff

    def apply(self, workdir: str, rule: str) -> None:
        subprocess.run(self._cmd(rule), cwd=workdir, check=True)

    def revert(self, workdir: str) -> None:
        _git_revert(workdir)


class ScriptReaudit:
    """Re-run the canonical audit over the patched tree (Run-Audit.ps1 -> findings.json)
    and load it back. This is the real no-new-findings oracle on the stand."""
    def __init__(self, run_audit_ps1: str, target: str, out_dir: str):
        self.script, self.target, self.out = run_audit_ps1, target, out_dir

    def __call__(self, workdir: str) -> list[Finding]:
        subprocess.run(["pwsh", self.script, "-Target", workdir, "-Out", self.out],
                       check=True)
        with open(os.path.join(self.out, "findings.json"), encoding="utf-8") as fh:
            return findings_from_obj(json.load(fh))
