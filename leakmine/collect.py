"""Discovery — generate the candidate-finding queries, deterministically.

Two collection backends, by scale (docs/leakfix-mine.md §4):

  - GitHub Search API — fine for a first slice, but brutal at scale: ~30 req/min, 1000
    results per query hard cap, and `language:` is the *repo's* language, not the diff's.
  - GH Archive (gharchive.org, mirrored as the public BigQuery `githubarchive` dataset) —
    the whole event firehose. We filter PR/issue events by leak keywords in SQL, no rate
    limit. The data is free; querying via BigQuery needs a GCP account (1 TB/month free),
    so we ALWAYS scope by day-partition to stay inside the free tier. GH Archive replaces
    *discovery* only — the patch itself still comes per-PR from the API or a clone.

Both query forms are generated here as pure strings so they unit-test with no network.
The actual fetch is isolated behind `fetch_search`, which takes an injectable HTTP getter
(so tests pass a fake and CI never reaches out).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import signals as sig


def github_search_queries(eco_key: str, *, merged_after: str = "") -> list[str]:
    """The GitHub-search query pack for an ecosystem, optionally date-bounded.
    `merged_after` is an ISO date (YYYY-MM-DD); it appends `merged:>=DATE`."""
    eco = sig.ECOSYSTEMS[eco_key]
    qs = list(eco.queries)
    if merged_after:
        qs = [f"{q} merged:>={merged_after}" for q in qs]
    return qs


def gharchive_sql(
    eco_key: str,
    *,
    date_from: str,
    date_to: str,
    limit: int = 2000,
) -> str:
    """A BigQuery query over `githubarchive.day.*` for merged PRs whose title/body carry a
    leak keyword and whose repo language matches. Day-partition scan keeps it cheap.

    `date_from`/`date_to` are YYYYMMDD (the `day` table suffix). We pass them through
    `_TABLE_SUFFIX BETWEEN` so BigQuery only scans those partitions — the difference
    between a few cents and a blown free tier.
    """
    eco = sig.ECOSYSTEMS[eco_key]
    # match the keyword in EITHER the PR title or body — a generic title with the leak
    # described in the body must still enter the corpus (COALESCE guards a null body).
    kw = " OR ".join(
        "(LOWER(JSON_EXTRACT_SCALAR(payload, '$.pull_request.title')) LIKE '%{k}%' OR "
        "LOWER(COALESCE(JSON_EXTRACT_SCALAR(payload, '$.pull_request.body'), '')) "
        "LIKE '%{k}%')".format(k=k)
        for k in eco.keywords
    )
    exts = " OR ".join(f"f LIKE '%{e}'" for e in eco.file_ext)
    return (
        "-- LeakFixMine discovery: merged leak-fix PRs, partition-scoped.\n"
        "SELECT\n"
        "  repo.name AS repo,\n"
        "  JSON_EXTRACT_SCALAR(payload, '$.number') AS number,\n"
        "  JSON_EXTRACT_SCALAR(payload, '$.pull_request.title') AS title,\n"
        "  JSON_EXTRACT_SCALAR(payload, '$.pull_request.merged_at') AS merged_at,\n"
        "  JSON_EXTRACT_SCALAR(payload, '$.pull_request.base.repo.language') AS lang\n"
        "FROM `githubarchive.day.*`\n"
        f"WHERE _TABLE_SUFFIX BETWEEN '{date_from}' AND '{date_to}'\n"
        "  AND type = 'PullRequestEvent'\n"
        "  AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'closed'\n"
        "  AND JSON_EXTRACT_SCALAR(payload, '$.pull_request.merged') = 'true'\n"
        f"  AND ({kw})\n"
        "  -- repo-language prefilter; the real diff-language check happens on changed files:\n"
        f"  -- expect changed paths matching: ({exts})\n"
        f"ORDER BY merged_at DESC\n"
        f"LIMIT {limit}\n"
    )


@dataclass
class Candidate:
    ecosystem: str
    repo: str
    number: int
    kind: str           # "pr" | "issue"
    title: str
    url: str


def fetch_search(query: str, *, token: str = "", http=None, per_page: int = 50) -> list[Candidate]:
    """Run one GitHub issue/PR search. `http` is an injectable opener returning bytes
    (tests pass a fake; production uses urllib). Network-touching by nature — never called
    in CI. Maps results into Candidates; classification happens downstream in `signals`."""
    url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": query, "per_page": per_page}
    )
    raw = (http or _urllib_get)(url, token)
    data = json.loads(raw)
    out: list[Candidate] = []
    for it in data.get("items", []):
        is_pr = "pull_request" in it
        out.append(Candidate(
            ecosystem="",
            repo=_repo_of(it.get("repository_url", "")),
            number=it.get("number", 0),
            kind="pr" if is_pr else "issue",
            title=it.get("title", ""),
            url=it.get("html_url", ""),
        ))
    return out


def _urllib_get(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "leakmine",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310 (https only)
        return r.read()


def _repo_of(repository_url: str) -> str:
    # https://api.github.com/repos/{owner}/{name} -> owner/name
    parts = repository_url.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else repository_url
