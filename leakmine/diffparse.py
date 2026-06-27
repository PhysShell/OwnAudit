"""Unified-diff parser — the substrate for patch signals and SZZ attribution.

A fix PR is, for our purposes, a unified diff. Two questions get asked of it over and
over: (1) *what text did it add/remove* (patch signals — `signals.py`), and (2) *which
old-file line numbers did it touch* (historical attribution — `szz.py`). Both need the
hunk structure, so we parse it once here.

Pure stdlib, no `git` and no `difflib` dependency: the parser eats the textual diff that
either `git show`/`git diff` or the GitHub patch endpoint hands us. We track BOTH sides'
line numbers because the two consumers look at opposite sides — signals care about added
(new-side) and removed (old-side) text; SZZ attribution maps a *pre-fix* finding (old
side) onto removed-line ranges.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# `@@ -oldStart,oldLen +newStart,newLen @@ optional section heading`
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
# `diff --git a/path b/path` and the `+++ b/path` / `--- a/path` forms.
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    # 1-based OLD-file line numbers that the hunk deletes (or replaces).
    removed_lines: set[int] = field(default_factory=set)
    # 1-based NEW-file line numbers that the hunk adds.
    added_lines: set[int] = field(default_factory=set)
    added_text: list[str] = field(default_factory=list)
    removed_text: list[str] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False        # /dev/null -> file (pure add)
    is_delete: bool = False     # file -> /dev/null (pure delete)
    is_rename: bool = False

    @property
    def path(self) -> str:
        """The post-fix path, or the pre-fix path for a deletion."""
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    def added_text(self) -> list[str]:
        out: list[str] = []
        for h in self.hunks:
            out.extend(h.added_text)
        return out

    def removed_text(self) -> list[str]:
        out: list[str] = []
        for h in self.hunks:
            out.extend(h.removed_text)
        return out

    def touches_old_line(self, line: int, window: int = 0) -> bool:
        """Did the fix delete/replace OLD-file `line` (± `window` for context)?

        This is the SZZ intersection test: a pre-fix finding anchored at `line` is
        *causally* linked to the fix only if the fix actually removed or replaced that
        line. `window` lets a near-miss (the fix added a `-=` two lines below the `+=`
        the finding flagged) still count, but keep it small or you re-admit luck.
        """
        for h in self.hunks:
            for rl in h.removed_lines:
                if abs(rl - line) <= window:
                    return True
            # a pure insertion (no removed line) still "touches" the spot it splits.
            if window and not h.removed_lines:
                lo, hi = h.old_start - window, h.old_start + window
                if lo <= line <= hi:
                    return True
        return False


def parse_patch(text: str) -> list[FileDiff]:
    """Parse a multi-file unified diff into FileDiffs. Tolerant of git extended
    headers (rename/new file/deleted file/index) and of bare `--- / +++` patches."""
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0

    for raw in text.splitlines():
        m = _DIFF_GIT_RE.match(raw)
        if m:
            cur = FileDiff(old_path=m.group(1), new_path=m.group(2))
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            # patch without a `diff --git` header — synthesize a file on first `---`.
            if raw.startswith("--- "):
                cur = FileDiff(old_path="", new_path="")
                files.append(cur)
            else:
                continue

        if raw.startswith("new file mode"):
            cur.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            cur.is_delete = True
            continue
        if raw.startswith("rename from") or raw.startswith("rename to"):
            cur.is_rename = True
            continue
        if raw.startswith("--- "):
            mo = _OLD_FILE_RE.match(raw)
            if mo:
                cur.old_path = mo.group(1)
            continue
        if raw.startswith("+++ "):
            mn = _NEW_FILE_RE.match(raw)
            if mn:
                cur.new_path = mn.group(1)
            continue

        hm = _HUNK_RE.match(raw)
        if hm:
            hunk = Hunk(
                old_start=int(hm.group(1)),
                old_len=int(hm.group(2) or "1"),
                new_start=int(hm.group(3)),
                new_len=int(hm.group(4) or "1"),
            )
            cur.hunks.append(hunk)
            old_no = hunk.old_start
            new_no = hunk.new_start
            continue

        if hunk is None:
            continue

        # body lines: ' ' context, '+' add, '-' remove, '\' no-newline marker.
        tag = raw[:1]
        body = raw[1:]
        if tag == "+":
            hunk.added_lines.add(new_no)
            hunk.added_text.append(body)
            new_no += 1
        elif tag == "-":
            hunk.removed_lines.add(old_no)
            hunk.removed_text.append(body)
            old_no += 1
        elif tag == "\\":
            continue  # "\ No newline at end of file"
        else:
            old_no += 1
            new_no += 1

    return files


def added_text(patch: str) -> list[str]:
    """All added lines across the whole patch (convenience for signal scoring)."""
    out: list[str] = []
    for fd in parse_patch(patch):
        out.extend(fd.added_text())
    return out


def removed_text(patch: str) -> list[str]:
    out: list[str] = []
    for fd in parse_patch(patch):
        out.extend(fd.removed_text())
    return out


def changed_paths(patch: str) -> list[str]:
    return [fd.path for fd in parse_patch(patch)]
