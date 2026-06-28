"""BigQuery arm — discovery (and a zero-fetch syntactic sweep) at firehose scale.

The Search-API path (`collect`/`mine`) tops out around a few thousand candidates per run
(1000-result cap, ~30 req/min, the per-PR diff-fetch wall). For 10k–millions, BigQuery is
the backend (docs/leakfix-mine.md §4, §14). Two products, with very different cost:

  1. GH Archive discovery (`gharchive_discovery_sql`) — the public `githubarchive.day.*`
     event firehose. One partition-scoped query returns every merged PR whose title OR body
     carries a leak keyword, in the target language, optionally size-capped to drop mega-
     refactors. CHEAP: scanning a bounded date range is a few hundred MB–few GB (well inside
     the 1 TB/month free tier). This REPLACES discovery — but GH Archive has no diffs, so the
     output is *metadata candidates* you then narrow-fetch + classify with `mine`/`collect`.

  2. Contents sweep (`contents_sweep_sql`) — `bigquery-public-data.github_repos`, a snapshot
     of file *contents*. Runs the SYNTACTIC tier (acquire-without-cleanup, e.g. an
     `addEventListener(` with no `removeEventListener`) as SQL regex over millions of files,
     ZERO fetch. EXPENSIVE: any query touching `contents.content` scans the full ~2.7 TB
     column regardless of filters (~$13, blows the free tier), so this defaults to the much
     smaller `sample_contents`/`sample_files` tables. Use the full tables only deliberately.

`ingest_rows` closes the loop: BigQuery results exported as NDJSON flow back into the leakmine
store, scored at the *metadata tier* (keyword strength + PR-size heuristic — NOT the patch
signal, which needs the diff). Pure stdlib; SQL generation + ingest unit-test offline.
"""
from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from . import schema, signals


# ---- GH Archive discovery (events) -----------------------------------------------

def gharchive_discovery_sql(
    eco_key: str,
    *,
    date_from: str,
    date_to: str,
    max_changed_files: int = 80,
    limit: int = 50000,
) -> str:
    """SQL over `githubarchive.day.*` for merged leak-fix PR candidates in one ecosystem.

    `date_from`/`date_to` are YYYYMMDD `day`-table suffixes; the `_TABLE_SUFFIX BETWEEN`
    bound is what keeps the scan cheap — never run this unbounded. `max_changed_files` drops
    mega-PRs where a leak keyword is incidental (set 0 to disable). Dedups to one row per PR.
    """
    eco = signals.ECOSYSTEMS[eco_key]
    kw = " OR ".join(
        "(LOWER(JSON_EXTRACT_SCALAR(payload,'$.pull_request.title')) LIKE '%{k}%' OR "
        "LOWER(COALESCE(JSON_EXTRACT_SCALAR(payload,'$.pull_request.body'),'')) "
        "LIKE '%{k}%')".format(k=k)
        for k in eco.keywords
    )
    langs = " OR ".join(
        f"LOWER(JSON_EXTRACT_SCALAR(payload,'$.pull_request.base.repo.language')) = '{lang}'"
        for lang in signals.LANGS.get(eco_key, ())
    ) or "TRUE"
    size_cap = (
        f"\n  AND SAFE_CAST(JSON_EXTRACT_SCALAR(payload,'$.pull_request.changed_files') "
        f"AS INT64) <= {max_changed_files}"
        if max_changed_files else ""
    )
    return (
        f"-- LeakFixMine GH-Archive discovery: ecosystem={eco_key}, "
        f"partitions {date_from}..{date_to}. Cost = bytes in those day-partitions only.\n"
        "SELECT\n"
        "  repo.name AS repo,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.number') AS number,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.title') AS title,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.body') AS body,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.merged_at') AS merged_at,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.base.repo.language') AS lang,\n"
        "  SAFE_CAST(JSON_EXTRACT_SCALAR(payload,'$.pull_request.changed_files') AS INT64) "
        "AS changed_files,\n"
        "  SAFE_CAST(JSON_EXTRACT_SCALAR(payload,'$.pull_request.additions') AS INT64) "
        "AS additions,\n"
        "  SAFE_CAST(JSON_EXTRACT_SCALAR(payload,'$.pull_request.deletions') AS INT64) "
        "AS deletions,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.html_url') AS html_url,\n"
        "  JSON_EXTRACT_SCALAR(payload,'$.pull_request.diff_url') AS diff_url\n"
        "FROM `githubarchive.day.*`\n"
        f"WHERE _TABLE_SUFFIX BETWEEN '{date_from}' AND '{date_to}'\n"
        "  AND type = 'PullRequestEvent'\n"
        "  AND JSON_EXTRACT_SCALAR(payload,'$.action') = 'closed'\n"
        "  AND JSON_EXTRACT_SCALAR(payload,'$.pull_request.merged') = 'true'\n"
        f"  AND ({kw})\n"
        f"  AND ({langs}){size_cap}\n"
        "-- one row per PR (the firehose repeats events):\n"
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY repo.name, "
        "JSON_EXTRACT_SCALAR(payload,'$.number') ORDER BY created_at DESC) = 1\n"
        f"LIMIT {limit}\n"
    )


# ---- Contents sweep (code snapshot, zero fetch) ----------------------------------

# acquire-without-cleanup pairs: a file containing `acquire` but not `cleanup` is a
# candidate syntactic-tier leak site. Regexes are RE2 (BigQuery REGEXP_CONTAINS).
SWEEP_PAIRS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "react_ts": (
        (r"addEventListener\(", r"removeEventListener", "listener"),
        (r"setInterval\(", r"clearInterval", "timer"),
        (r"\.subscribe\(", r"unsubscribe", "subscription"),
    ),
    "dotnet_wpf": (
        (r"new DispatcherTimer", r"\.Stop\(", "timer"),
        (r"new FileSystemWatcher", r"\.Dispose\(", "idisposable"),
    ),
    "java_spring": (
        (r"newFixedThreadPool|newCachedThreadPool", r"\.shutdown", "executor"),
        (r"new ThreadLocal", r"\.remove\(", "static-retention"),
    ),
    "android_kotlin": (
        (r"registerReceiver\(", r"unregisterReceiver", "subscription"),
    ),
}


def contents_sweep_sql(
    eco_key: str,
    *,
    sample: bool = True,
    limit: int = 5000,
) -> str:
    """SQL over `github_repos` that flags syntactic-tier leak sites with zero fetch.

    `sample=True` (default) targets `sample_files`/`sample_contents` — far cheaper. The full
    `files`/`contents` tables scan the ~2.7 TB content column on any reference (≈$13/query),
    so flip `sample` off only when you mean it. Returns (repo, path, signal) candidate sites.
    """
    pairs = SWEEP_PAIRS.get(eco_key, ())
    if not pairs:
        raise ValueError(f"no contents-sweep pairs defined for ecosystem {eco_key!r}")
    files_tbl = "sample_files" if sample else "files"
    contents_tbl = "sample_contents" if sample else "contents"
    exts = " OR ".join(f"f.path LIKE '%{e}'" for e in signals.ECOSYSTEMS[eco_key].file_ext)
    cases = "\n".join(
        f"    WHEN REGEXP_CONTAINS(c.content, r'{acq}') "
        f"AND NOT REGEXP_CONTAINS(c.content, r'{cln}') THEN '{label}'"
        for acq, cln, label in pairs
    )
    # candidate = acquire present AND its cleanup absent — for at least one pair. Without the
    # NOT-cleanup half a *balanced* file (acquire + cleanup) would still match and fall through
    # the CASE to 'other', flooding the sweep with non-leaks. So the WHERE mirrors the CASE.
    candidate_pred = " OR ".join(
        f"(REGEXP_CONTAINS(c.content, r'{acq}') AND NOT REGEXP_CONTAINS(c.content, r'{cln}'))"
        for acq, cln, _ in pairs
    )
    return (
        f"-- LeakFixMine contents sweep: ecosystem={eco_key}, table="
        f"{'sample_' if sample else ''}(files/contents). "
        f"{'CHEAP sample.' if sample else 'WARNING: full content scan ~2.7TB (~$13).'}\n"
        "SELECT f.repo_name AS repo, f.path AS path,\n"
        "  CASE\n"
        f"{cases}\n"
        "  END AS signal\n"
        f"FROM `bigquery-public-data.github_repos.{files_tbl}` f\n"
        f"JOIN `bigquery-public-data.github_repos.{contents_tbl}` c USING (id)\n"
        f"WHERE ({exts})\n"
        "  AND NOT c.binary\n"
        f"  AND ({candidate_pred})\n"
        f"LIMIT {limit}\n"
    )


# ---- ingest: BigQuery NDJSON -> leakmine store (metadata tier) --------------------

@dataclass
class MetaResult:
    ecosystem: str
    rows: list[dict] = field(default_factory=list)
    seen: int = 0
    kept: int = 0
    known: int = 0          # candidates already in the store (skipped — cross-run dedup)

    def summary_md(self) -> str:
        return (
            f"# LeakFixMine — BigQuery ingest (`{self.ecosystem}`, metadata tier)\n\n"
            f"- rows seen: **{self.seen}**\n"
            f"- already in store (skipped): **{self.known}**\n"
            f"- kept (>= meta threshold): **{self.kept}**\n\n"
            "NOTE: metadata-tier score (keyword + PR size), NOT the patch signal. "
            "Narrow-fetch the kept PRs and run `mine`/`confirm` for the real classification.\n"
        )


def metadata_score(eco_key: str, *, title: str = "", body: str = "",
                   changed_files: int | None = None) -> tuple[int, list[str]]:
    """Discovery-tier score for a PR we have metadata-only for (no diff yet).

    +3 leak keyword in title, +2 in body; PR-size shaping so a focused fix outranks a mega-
    refactor where the keyword is incidental. This is deliberately weaker than the patch
    classifier — it ranks the fetch queue, it does not assign a leak category.
    """
    eco = signals.ECOSYSTEMS[eco_key]
    score, ev = 0, []
    tl, bl = (title or "").lower(), (body or "").lower()
    if any(k in tl for k in eco.keywords):
        score += 3
        ev.append("title:leak-keyword")
    if any(k in bl for k in eco.keywords):
        score += 2
        ev.append("body:leak-keyword")
    if changed_files is not None:
        if changed_files <= 10:
            score += 2
            ev.append("small-pr")
        elif changed_files > 200:
            score -= 3
            ev.append("penalty:mega-pr")
    return score, ev


def ingest_rows(rows: Iterable[dict], eco_key: str, *, min_meta_score: int = 4,
                conn=None) -> MetaResult:
    """Ingest exported BigQuery rows (dicts with the SELECT-alias keys) into the store.

    `rows` is any iterable — pass `iter_ndjson(path)` to stream a multi-GB export without
    loading it into memory. Dedups by (repo, number), scores at the metadata tier, keeps
    >= `min_meta_score`. With a `conn` it writes candidates + a 'bigquery-meta' label so the
    rest of the pipeline (fetch + `signals.classify` + `confirm`) can pick the survivors up.
    """
    res = MetaResult(ecosystem=eco_key)
    rows = iter(rows)
    try:
        first = next(rows)
    except StopIteration:
        return res
    # Fail fast on the wrong export: contents-sweep rows are (repo, path, signal) with no PR
    # number, and there's no PR metadata to score — they ARE the candidate set, consume that
    # export directly. Silently dropping them (they'd just miss the repo+number gate) would be
    # a footgun, so reject explicitly. bq-ingest is GH-Archive-discovery only.
    if "number" not in first and ("path" in first or "signal" in first):
        raise ValueError(
            "these look like contents-sweep rows (repo/path/signal); bq-ingest takes only "
            "GH-Archive discovery rows (repo/number). The contents-sweep export is already the "
            "candidate set — use it directly, there is no PR metadata to score."
        )
    rows = itertools.chain([first], rows)
    seen: set[tuple[str, str]] = set()
    # Cross-run dedup: candidates already in the store are skipped, so re-ingesting an
    # overlapping date window (to GROW the corpus) never re-scores/re-writes a PR we already
    # hold. Pre-load the existing id set once (cheap vs a per-row SELECT). New keys are added
    # to it as we go, so a duplicate within THIS export is caught too.
    known_ids: set[str] = set()
    if conn is not None:
        known_ids = {
            r[0] for r in conn.execute(
                "SELECT id FROM candidates WHERE ecosystem = ?", (eco_key,)
            )
        }
    for r in rows:
        repo, number = r.get("repo", ""), str(r.get("number", ""))
        if not repo or not number:
            continue
        key = (repo, number)
        if key in seen:
            continue
        seen.add(key)
        cid = f"{repo}#{number}"
        if cid in known_ids:
            res.known += 1
            continue
        known_ids.add(cid)
        res.seen += 1
        cf = r.get("changed_files")
        cf = int(cf) if cf not in (None, "") else None
        score, ev = metadata_score(eco_key, title=r.get("title", ""), body=r.get("body", ""),
                                   changed_files=cf)
        if score < min_meta_score:
            continue
        res.kept += 1
        row = {
            "ecosystem": eco_key, "repo": repo, "number": int(number),
            "url": r.get("html_url") or r.get("diff_url") or "",
            "title": r.get("title", ""), "meta_score": score, "evidence": ev,
            "changed_files": cf,
        }
        res.rows.append(row)
        if conn is not None:
            schema.insert_candidate(conn, {
                "id": f"{repo}#{number}", "ecosystem": eco_key, "query": "bigquery:gharchive",
                "repo": repo, "number": int(number), "kind": "pr",
                "title": r.get("title", ""), "body": r.get("body", ""),
                "state": "merged", "merged": 1, "url": row["url"],
            })
            schema.insert_label(conn, f"{repo}#{number}", "metadata-candidate", score, ev,
                                "bigquery-meta")
    return res


def read_ndjson(text: str) -> list[dict]:
    """Parse an in-memory NDJSON string (one JSON object per line; blanks ignored)."""
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def iter_ndjson(path: str) -> Iterator[dict]:
    """Stream an NDJSON export file line-by-line — never materialises the whole dump, so a
    multi-GB BigQuery export ingests at bounded memory (the only in-memory state downstream
    is the (repo, number) dedup set)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
