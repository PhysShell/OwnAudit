"""Duplicate-key detection for the raw JSON parse, shared by both suites.

`json.load` keeps the last of a duplicated key and drops the other without a
word. Every contract and every fixture in this project is read BY KEY, so a
duplicated key silently deletes half of what a document says before any check
sees it - a rule, a limitation, an evidence kind, or half a preregistered
expectation.

This lived inside `test_lineage_decision.py`, where it scanned that suite's two
contracts and one fixture directory. The eligibility corpus arrived later and
never joined the list; the SENIOR suite never had a scan at all, and its
thirteen cases carry the same exposure - verified by injecting a second
`expect` into `added-file-is-an-evidenced-birth`, which left that suite green.
It is here rather than copied into the second suite because a second copy of a
checker is a checker that will disagree with itself, which is the defect this
project keeps finding in its own drafts.
"""
import json


class _Marked(dict):
    """A parsed JSON object that remembers the keys declared twice inside it.

    A plain dict cannot carry that fact to a later walk; this can."""
    __slots__ = ("duplicate_keys",)


def duplicate_json_keys(path: str) -> list:
    """Dotted paths to keys declared twice in ONE object, from the RAW parse.

    Two earlier versions of this function got its own description wrong, in
    opposite directions. The first promised dotted paths and returned bare names.
    The second returned the key plus its siblings and asserted that a path was not
    obtainable, because `object_pairs_hook` is called innermost-first and never
    learns where it is. That second claim was false: the hook does not know, but a
    walk from the root afterwards does, once each object carries what it saw. So
    the paths are real - `arbitration.conflict.reason`, not `reason` - and the
    docstring finally matches the code.

    Stating something impossible when it is merely inconvenient is the same defect
    this suite keeps finding elsewhere: a description that claims more, or less,
    than the code does."""
    def hook(pairs):
        obj = _Marked(pairs)
        seen, dups = set(), []
        for key, _ in pairs:
            if key in seen:
                dups.append(key)
            seen.add(key)
        obj.duplicate_keys = dups
        return obj

    with open(path, encoding="utf-8") as fh:
        root = json.load(fh, object_pairs_hook=hook)

    found: list = []

    def walk(node, trail):
        if isinstance(node, _Marked):
            for key in node.duplicate_keys:
                found.append(".".join(trail + [key]) or key)
            for key, value in node.items():
                walk(value, trail + [key])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, trail + [f"[{i}]"])

    walk(root, [])
    return sorted(set(found))
