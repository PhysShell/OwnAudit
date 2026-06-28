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


@dataclass
class EnrichResult:
    ecosystem: str
    repos: int = 0          # repos looked up this run
    labeled: int = 0        # candidates given a language label
    skipped: int = 0        # candidates marked wrong-language (won't be diff-fetched)
    by_lang: dict = field(default_factory=dict)

    def summary_md(self) -> str:
        lines = [
            f"# LeakFixMine — language enrichment (`{self.ecosystem}`)",
            "",
            f"- repos enriched: **{self.repos}**",
            f"- candidates labelled: **{self.labeled}**",
            f"- marked wrong-language (skipped before diff fetch): **{self.skipped}**",
            "",
            "| language | candidates |", "|---|---:|",
        ]
        for lang, n in sorted(self.by_lang.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {lang or 'unknown'} | {n} |")
        return "\n".join(lines) + "\n"


def enrich_languages(
    conn,
    eco_key: str,
    *,
    token: str = "",
    batch: int = 100,
    limit=None,
    fetch_languages=None,
) -> EnrichResult:
    """Enrich stored candidates with their repo's primary language (batched GraphQL) and mark
    cross-language ones so `classify_from_store` skips them BEFORE the expensive diff fetch.

    Run between `bq-ingest` and `classify-store`. For each candidate it writes a
    `classifier='language'` label (record), and if the repo language is known and NOT in this
    ecosystem's `signals.LANGS`, also a `classifier='patch'` label `wrong-language` — which the
    classify-store anti-join already excludes, so no diff is fetched for it. Unknown languages
    are left for classify-store to try. Resumable: repos already language-labelled are skipped.
    """
    fetch_languages = fetch_languages or collect.fetch_repo_languages
    target = set(signals.LANGS.get(eco_key, ()))
    res = EnrichResult(ecosystem=eco_key)
    sql = (
        "SELECT DISTINCT c.repo FROM candidates c "
        "LEFT JOIN labels lg ON lg.candidate_id = c.id AND lg.classifier = 'language' "
        "LEFT JOIN labels lp ON lp.candidate_id = c.id AND lp.classifier = 'patch' "
        "WHERE c.ecosystem = ? AND c.kind = 'pr' "
        "AND lg.candidate_id IS NULL AND lp.candidate_id IS NULL ORDER BY c.repo"
    )
    params = [eco_key]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    repos = [row[0] for row in conn.execute(sql, params)]
    if not repos:
        return res
    langs = fetch_languages(repos, token=token, batch=batch)
    for repo in repos:
        if repo not in langs:
            continue            # lookup failed for this repo's batch — leave it for a retry
        lang = langs[repo]
        res.repos += 1
        # Only the repo's UNPROCESSED candidates — mirror the repo-list anti-join. A repo can
        # have one pending PR and one already-classified/-language-labelled PR; re-scanning the
        # whole repo here would write a duplicate `language` row (and a second wrong-language
        # `patch` label) onto the already-processed candidate. This is also the cross-run dedup:
        # a later enrich pass over an overlapping window touches only genuinely new candidates.
        rows = conn.execute(
            "SELECT c.id FROM candidates c "
            "LEFT JOIN labels lg ON lg.candidate_id = c.id AND lg.classifier = 'language' "
            "LEFT JOIN labels lp ON lp.candidate_id = c.id AND lp.classifier = 'patch' "
            "WHERE c.ecosystem = ? AND c.kind = 'pr' AND c.repo = ? "
            "AND lg.candidate_id IS NULL AND lp.candidate_id IS NULL",
            (eco_key, repo),
        ).fetchall()
        for (cid,) in rows:
            schema.insert_label(conn, cid, lang or "unknown", 0, [], "language")
            res.labeled += 1
            res.by_lang[lang] = res.by_lang.get(lang, 0) + 1
            if target and lang and lang not in target:
                schema.insert_label(conn, cid, "wrong-language", 0, [], "patch")
                res.skipped += 1
        conn.commit()
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
    is injected as a fake in tests. Labels are committed PER ATTEMPT (not just at the end),
    so a crash/kill mid-run doesn't roll back resume progress and re-burn diff quota.

    RESUMABLE: every attempted PR gets a `classifier='patch'` label — the real category when
    kept, `below-threshold` for a fetched-but-low-score miss, `fetch-failed` when no diff came
    back — and any PR that already has such a label is skipped BEFORE `--limit` is counted. So
    `--limit`-sized batches (and reruns after an interruption) advance through the queue
    instead of re-burning diff quota on the same head. To retry failures, delete their
    `fetch-failed` labels.
    """
    fetch_patch = fetch_patch or collect.fetch_patch
    res = MineResult(ecosystem=eco_key)
    # Exclude already-attempted candidates IN SQL (anti-join on a patch-tier label) and push
    # --limit into the query, so reruns/batches stream only the unprocessed head instead of
    # loading the whole table and re-burning diff quota. ORDER BY c.id makes the batch order
    # stable (and materialises the result, so the in-loop label inserts can't disturb it).
    sql = (
        "SELECT c.repo, c.number, c.title, c.body FROM candidates AS c "
        "LEFT JOIN labels AS l ON l.candidate_id = c.id AND l.classifier = 'patch' "
        "WHERE c.ecosystem = ? AND c.kind = 'pr' AND l.candidate_id IS NULL "
        "ORDER BY c.id"
    )
    params = [eco_key]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    for repo, number, title, body in conn.execute(sql, params):
        cid = f"{repo}#{number}"
        res.seen += 1
        patch = fetch_patch(repo, number, token=token)
        if sleep:
            time.sleep(sleep)
        if not patch:
            schema.insert_label(conn, cid, "fetch-failed", 0, [], "patch")
            conn.commit()                        # persist progress per attempt (crash-safe resume)
            continue
        res.fetched += 1
        cls = signals.classify(eco_key, title=title or "", body=body or "", patch=patch)
        if cls.score < min_score:
            schema.insert_label(conn, cid, "below-threshold", cls.score, cls.evidence, "patch")
            conn.commit()
            continue
        res.kept += 1
        res.rows.append({
            "ecosystem": eco_key, "repo": repo, "number": number,
            "title": title, "category": cls.category, "score": cls.score,
            "is_likely_fix": cls.is_likely_fix, "evidence": cls.evidence,
        })
        schema.insert_label(conn, cid, cls.category, cls.score, cls.evidence, "patch")
        conn.commit()
    return res
