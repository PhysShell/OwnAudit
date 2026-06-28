"""Mining orchestrator — discover → fetch patch → classify → store, one ecosystem at a time.

This is the CI-runnable arm of the pipeline (docs/leakfix-mine.md §4/§10). It chains the
GitHub-Search query pack (`collect.github_search_queries`) → per-PR patch fetch
(`collect.fetch_patch`) → patch-signal classification (`signals.classify`), dedups by
(repo, number), keeps everything scoring at/above the candidate threshold, and writes the
result to the SQLite store plus a JSON dataset and a markdown summary.

Deliberately scoped to **discovery + classification** — the part that runs cleanly on a
hosted runner with only `GITHUB_TOKEN`. The before/after tool comparison (`confirm` /
`metrics`) needs per-repo checkout + analyzer builds, so it stays a local / self-hosted
step; see docs/leakfix-mine.md §7.

Network access is isolated behind the injected `search` / `fetch_patch` callables, so the
orchestration unit-tests offline with fakes (CI never reaches out).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import collect, schema, signals


@dataclass
class MineResult:
    ecosystem: str
    rows: list[dict] = field(default_factory=list)   # one per kept candidate
    seen: int = 0                                     # candidates examined (post-dedup)
    fetched: int = 0                                  # patches successfully fetched
    kept: int = 0                                     # candidates >= min_score

    def summary_md(self) -> str:
        by_cat: dict[str, int] = {}
        for r in self.rows:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        lines = [
            f"# LeakFixMine — `{self.ecosystem}` mining run",
            "",
            f"- candidates examined: **{self.seen}**",
            f"- patches fetched: **{self.fetched}**",
            f"- kept (>= threshold): **{self.kept}**",
            "",
            "## kept by category",
            "",
            "| category | kept |",
            "|---|---:|",
        ]
        for cat, c in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {cat} | {c} |")
        lines += ["", "## kept candidates", "", "| score | category | repo#PR | title |",
                  "|---:|---|---|---|"]
        for r in sorted(self.rows, key=lambda r: -r["score"])[:100]:
            title = (r["title"] or "").replace("|", "\\|")[:80]
            lines.append(f"| {r['score']} | {r['category']} | {r['repo']}#{r['number']} | {title} |")
        return "\n".join(lines) + "\n"


def run(
    ecosystem: str,
    *,
    token: str = "",
    merged_after: str = "",
    per_query: int = 50,
    min_score: int = 7,
    sleep: float = 0.0,
    conn=None,
    search=None,
    fetch_patch=None,
) -> MineResult:
    """Mine one ecosystem. `search(query, *, token, per_page) -> list[Candidate]` and
    `fetch_patch(repo, number, *, token) -> str` default to the live `collect` helpers but
    are injected as fakes in tests. `sleep` throttles between API calls to stay under the
    Search API's ~30 req/min; pass 0 in tests."""
    search = search or collect.fetch_search
    fetch_patch = fetch_patch or collect.fetch_patch

    res = MineResult(ecosystem=ecosystem)
    seen: set[tuple[str, int]] = set()

    for query in collect.github_search_queries(ecosystem, merged_after=merged_after):
        candidates = search(query, token=token, per_page=per_query)
        if sleep:
            time.sleep(sleep)
        for cand in candidates:
            key = (cand.repo, cand.number)
            if cand.kind != "pr" or key in seen:
                continue
            seen.add(key)
            res.seen += 1

            patch = fetch_patch(cand.repo, cand.number, token=token)
            if sleep:
                time.sleep(sleep)
            if not patch:
                continue
            res.fetched += 1

            cls = signals.classify(ecosystem, title=cand.title, body=cand.body, patch=patch)
            if cls.score < min_score:
                continue
            res.kept += 1
            row = {
                "ecosystem": ecosystem,
                "repo": cand.repo,
                "number": cand.number,
                "url": cand.url,
                "title": cand.title,
                "category": cls.category,
                "score": cls.score,
                "is_candidate": cls.is_candidate,
                "is_likely_fix": cls.is_likely_fix,
                "evidence": cls.evidence,
            }
            res.rows.append(row)
            if conn is not None:
                schema.insert_candidate(conn, {
                    "id": f"{cand.repo}#{cand.number}", "ecosystem": ecosystem,
                    "query": query, "repo": cand.repo, "number": cand.number,
                    "kind": "pr", "title": cand.title, "body": cand.body,
                    "state": "merged", "merged": 1, "url": cand.url,
                })
                schema.insert_label(conn, f"{cand.repo}#{cand.number}", cls.category,
                                    cls.score, cls.evidence, "patch")
    return res


def classify_from_store(
    conn,
    eco_key: str,
    *,
    token: str = "",
    min_score: int = 7,
    sleep: float = 0.0,
    limit=None,
    fetch_patch=None,
) -> MineResult:
    """Close the loop: take the candidate PRs already in the store (from a BigQuery /
    GH-Archive ingest, which only had title/body metadata), fetch each diff, and run the
    REAL patch-tier `signals.classify`. The metadata tier was a fetch *queue*; this is the
    verdict — category + patch-signal score, kept at `min_score`.

    `fetch_patch(repo, number, *, token) -> str` defaults to the live `collect` helper and
    is injected as a fake in tests. Writes a 'patch'-classifier label per kept PR so the
    metadata and patch verdicts coexist in the store.
    """
    fetch_patch = fetch_patch or collect.fetch_patch
    res = MineResult(ecosystem=eco_key)
    cur = conn.execute(
        "SELECT repo, number, title, body FROM candidates WHERE ecosystem=? AND kind='pr'",
        (eco_key,),
    )
    for repo, number, title, body in cur.fetchall():
        if limit is not None and res.seen >= limit:
            break
        res.seen += 1
        patch = fetch_patch(repo, number, token=token)
        if sleep:
            time.sleep(sleep)
        if not patch:
            continue
        res.fetched += 1
        cls = signals.classify(eco_key, title=title or "", body=body or "", patch=patch)
        if cls.score < min_score:
            continue
        res.kept += 1
        res.rows.append({
            "ecosystem": eco_key, "repo": repo, "number": number,
            "title": title, "category": cls.category, "score": cls.score,
            "is_likely_fix": cls.is_likely_fix, "evidence": cls.evidence,
        })
        schema.insert_label(conn, f"{repo}#{number}", cls.category, cls.score,
                            cls.evidence, "patch")
    return res
