"""AI fixer — a pluggable `Applier` that proposes patches with a LOCAL LLM for the
findings mechanical fixers can't touch (T3 detect-only, T4-refused suggest-only).

The whole point: the model is *not* trusted. It plugs into the same wrapper as every
other applier (orchestrate.run_fix), so its patch is verified by re-running the audit
(removed the finding AND introduced nothing new?), shown as a reviewable diff, gated to
REVIEW (never auto-commit), and rolled back on regression. The LLM only proposes; the
audit and the human judge — which is why a local, modest model is safe here.

Local-only by design: code never leaves the machine. The client speaks the OpenAI
chat-completions API, so it works against Ollama (default), llama.cpp's server, LM
Studio, vLLM, etc. A MockLlmClient drives the same path in CI with no server.
"""
from __future__ import annotations

import json
import re
import urllib.request

from .own_fix import _safe_join   # reuse the path-traversal guard

SYSTEM = (
    "You are a careful C# code fixer. You are given a numbered code window and a "
    "static-analysis finding. Return ONLY the corrected replacement for the requested "
    "line range, inside a single ```csharp fenced block, preserving indentation and the "
    "surrounding behaviour. Make the MINIMAL change that resolves the finding. If you "
    "cannot fix it safely, return the original lines unchanged."
)

_FENCE = re.compile(r"```[A-Za-z0-9#+]*\n(.*?)```", re.S)


def build_user(rel: str, lines: list[str], a: int, b: int, finding) -> str:
    """Prompt body: the file, the finding, and the numbered window [a, b) to replace."""
    numbered = "".join(f"{i + 1:>5}  {lines[i]}" for i in range(a, b))
    return (f"File: {rel}\n"
            f"Finding at line {finding.line} [{finding.rule}]: {finding.message}\n\n"
            f"Replace lines {a + 1}..{b} (return only their corrected form):\n\n{numbered}")


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
    """Canned reply for CI — drives the exact same applier path with no server."""
    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


# ---- the applier -----------------------------------------------------------

class AiFixApplier:
    """For each finding, ask the LLM to rewrite a window around it; splice the reply
    back. Inherits dry-run/diff/re-audit/gate/rollback from the wrapper — so a wrong
    or no-op proposal is caught (rejected/skipped), never trusted. Always REVIEW."""
    name = "ai-fix"

    def __init__(self, findings, client, ctx: int = 12):
        self.findings = list(findings)
        self.client = client
        self.ctx = ctx
        self._orig: dict[str, str] = {}
        self.skipped: list = []

    def _by_file(self):
        byf: dict[str, list] = {}
        for f in self.findings:
            byf.setdefault(f.path, []).append(f)
        return byf

    def _plan(self, workdir: str):
        out, skipped = {}, []
        for rel, fs in self._by_file().items():
            with open(_safe_join(workdir, rel), encoding="utf-8") as fh:
                lines = fh.readlines()
            edits, occupied = [], set()
            for f in fs:
                a = max(0, f.line - 1 - self.ctx)
                b = min(len(lines), f.line - 1 + self.ctx + 1)
                if set(range(a, b)) & occupied:
                    skipped.append((f, "ai-overlap"))      # windows collide; one at a time
                    continue
                reply = self.client.complete(SYSTEM, build_user(rel, lines, a, b, f))
                repl = parse_replacement(reply)
                if repl is None or repl == lines[a:b]:
                    skipped.append((f, "ai-no-change"))     # model declined / unparseable
                    continue
                edits.append((a, b, repl))
                occupied |= set(range(a, b))
            new = list(lines)
            for s, e, repl in sorted(edits, key=lambda t: t[0], reverse=True):
                new[s:e] = repl
            out[rel] = "".join(new)
        self.skipped = skipped
        return out

    def dry_run(self, workdir: str, rule: str) -> str:
        import difflib
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
