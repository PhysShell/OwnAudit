"""AI fixer — a pluggable `Applier` that proposes patches with a LOCAL LLM for the
findings mechanical fixers can't touch (T3 detect-only, T4-refused suggest-only).

The model is *not* trusted. It plugs into the same wrapper as every other applier
(orchestrate.run_fix), so its patch is verified by re-running the audit (removed the
finding AND introduced nothing new?), shown as a reviewable diff, gated to REVIEW
(never auto-commit), and rolled back on regression. The LLM only proposes; the audit
and the human judge — which is why a modest local model is safe.

Optional verify→revise loop (no framework): when a `reaudit` is supplied, each proposal
is checked per round; if it doesn't clear the finding (or introduces new ones) the
failure is fed back and the model revises, up to `max_rounds`. Every round still goes
through the audit — the loop just helps a weaker local model converge.

Local-only by design: code never leaves the machine. The client speaks the OpenAI chat
API, so it works against Ollama (default), llama.cpp's server, LM Studio, vLLM. A
MockLlmClient drives the same path in CI with no server.
"""
from __future__ import annotations

import difflib
import json
import re
import urllib.request

from .orchestrate import diff_findings
from .own_fix import _safe_join   # reuse the path-traversal guard

SYSTEM = (
    "You are a careful C# code fixer. You are given a numbered code window and a "
    "static-analysis finding. Return ONLY the corrected replacement for the requested "
    "line range, inside a single ```csharp fenced block, preserving indentation and the "
    "surrounding behaviour. Make the MINIMAL change that resolves the finding. If you "
    "cannot fix it safely, return the original lines unchanged."
)

_FENCE = re.compile(r"```[A-Za-z0-9#+]*\n(.*?)```", re.S)


def build_user(rel: str, lines: list[str], a: int, b: int, finding, feedback: str = "") -> str:
    """Prompt body: the file, the finding, the numbered window [a, b) to replace, and
    (on a revise round) why the previous attempt was rejected."""
    numbered = "".join(f"{i + 1:>5}  {lines[i]}" for i in range(a, b))
    fb = f"\nYour previous attempt was rejected: {feedback}\nTry again.\n" if feedback else ""
    return (f"File: {rel}\n"
            f"Finding at line {finding.line} [{finding.rule}]: {finding.message}\n"
            f"{fb}\nReplace lines {a + 1}..{b} (return only their corrected form):\n\n{numbered}")


def parse_replacement(text: str):
    """Extract the first fenced block as replacement lines (keepends), or None."""
    m = _FENCE.search(text or "")
    if not m:
        return None
    out = m.group(1).splitlines(keepends=True)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    return out


# ---- LLM clients -----------------------------------------------------------

class LocalLlmClient:
    """OpenAI-compatible chat client for a LOCAL server. Default targets Ollama
    (`ollama serve` → http://localhost:11434/v1). No API key, nothing leaves the box."""
    name = "local-llm"

    def __init__(self, base_url="http://localhost:11434/v1",
                 model="qwen2.5-coder", timeout=180):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/chat/completions", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:   # local only
            data = json.load(r)
        return data["choices"][0]["message"]["content"]


class MockLlmClient:
    """Canned reply(ies) for CI — drives the same applier path with no server. A list
    is consumed one per call (last repeats), so a [bad, good] sequence tests the loop."""
    def __init__(self, reply):
        self._replies = reply if isinstance(reply, list) else [reply]
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        i = min(len(self.calls) - 1, len(self._replies) - 1)
        return self._replies[i]


# ---- the applier -----------------------------------------------------------

def _still_present(after, f) -> bool:
    return any(g.rule == f.rule and g.basename == f.basename and abs(g.line - f.line) <= 2
               for g in after)


class AiFixApplier:
    """For each finding, ask the LLM to rewrite a window around it; splice the reply
    back. Inherits dry-run/diff/re-audit/gate/rollback from the wrapper. With `reaudit`
    set, runs a verify→revise loop (each round re-audited) so the local model converges;
    without it, single-shot (the wrapper still verifies). Always REVIEW."""
    name = "ai-fix"

    def __init__(self, findings, client, reaudit=None, before=None, max_rounds=3, ctx=12):
        self.findings = list(findings)
        self.client = client
        self.reaudit = reaudit            # None -> single-shot; set -> revise loop
        self.before = list(before or [])
        self.max_rounds = max_rounds
        self.ctx = ctx
        self._orig: dict[str, str] = {}
        self._planned = None
        self.skipped: list = []

    def _by_file(self):
        byf: dict[str, list] = {}
        for f in self.findings:
            byf.setdefault(f.path, []).append(f)
        return byf

    def _propose(self, rel, cur, a, b, f, feedback=""):
        reply = self.client.complete(SYSTEM, build_user(rel, cur, a, b, f, feedback))
        repl = parse_replacement(reply)
        if repl is None or repl == cur[a:b]:
            return None                    # model declined / unparseable
        return cur[:a] + repl + cur[b:]

    def _revise(self, workdir, path, rel, cur, a, b, f, skipped):
        """Return the accepted candidate lines, or None (and record why in skipped)."""
        if self.reaudit is None:           # single-shot — wrapper verifies
            cand = self._propose(rel, cur, a, b, f)
            if cand is None:
                skipped.append((f, "ai-no-change"))
            return cand
        for _ in range(self.max_rounds):
            cand = self._propose(rel, cur, a, b, f, self._feedback)
            if cand is None:
                skipped.append((f, "ai-no-change"))
                return None
            with open(path, "w", encoding="utf-8") as fh:   # let re-audit see the candidate
                fh.write("".join(cand))
            after = self.reaudit(workdir)
            introduced = diff_findings(self.before, after)[1]
            if not _still_present(after, f) and not introduced:
                return cand                # verified this round
            with open(path, "w", encoding="utf-8") as fh:   # restore base for next round
                fh.write("".join(cur))
            self._feedback = ("it introduced new findings"
                              if introduced else "the finding is still reported")
        skipped.append((f, "ai-gave-up"))
        return None

    def _plan(self, workdir: str):
        if self._planned is not None:
            return self._planned
        out, skipped = {}, []
        for rel, fs in self._by_file().items():
            path = _safe_join(workdir, rel)
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
            cur, occupied = original.splitlines(keepends=True), set()
            self._feedback = ""
            for f in fs:
                a = max(0, f.line - 1 - self.ctx)
                b = min(len(cur), f.line - 1 + self.ctx + 1)
                if set(range(a, b)) & occupied:
                    skipped.append((f, "ai-overlap"))
                    continue
                accepted = self._revise(workdir, path, rel, cur, a, b, f, skipped)
                if accepted is not None:
                    cur, occupied = accepted, occupied | set(range(a, b))
            with open(path, "w", encoding="utf-8") as fh:   # planning is side-effect-free
                fh.write(original)
            out[rel] = "".join(cur)
        self._planned, self.skipped = out, skipped
        return out

    def dry_run(self, workdir: str, rule: str) -> str:
        chunks = []
        for rel, new in self._plan(workdir).items():
            with open(_safe_join(workdir, rel), encoding="utf-8") as fh:
                old = fh.readlines()
            chunks.extend(difflib.unified_diff(
                old, new.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return "".join(chunks)

    def apply(self, workdir: str, rule: str) -> None:
        for rel, new in self._plan(workdir).items():
            p = _safe_join(workdir, rel)
            if rel not in self._orig:
                with open(p, encoding="utf-8") as fh:
                    self._orig[rel] = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)

    def revert(self, workdir: str) -> None:
        for rel, orig in self._orig.items():
            with open(_safe_join(workdir, rel), "w", encoding="utf-8") as fh:
                fh.write(orig)
        self._orig.clear()
