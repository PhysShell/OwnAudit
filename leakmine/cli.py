"""LeakFixMine CLI — drive the research pipeline stage by stage (docs/leakfix-mine.md §12).

    python3 -m leakmine.cli queries  --ecosystem react_ts
    python3 -m leakmine.cli sql      --ecosystem dotnet_wpf --from 20240101 --to 20241231
    python3 -m leakmine.cli classify --ecosystem react_ts --patch fix.diff --title "fix leak"
    python3 -m leakmine.cli confirm  --candidate cand.json
    python3 -m leakmine.cli metrics  --verdicts verdicts.json
    python3 -m leakmine.cli sweep    --packages pkgs.json --n 50
    python3 -m leakmine.cli leadtime --repo PATH --sha SHA --file F --line N

Every stage reads/writes JSON so the steps compose in a shell pipeline; the SQLite store
(`schema.py`) is the durable spine for a real multi-day run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import bigquery, collect, confirm, metrics, mine, schema, signals, sweep, szz


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_queries(a) -> int:
    for q in collect.github_search_queries(a.ecosystem, merged_after=a.merged_after or ""):
        print(q)
    return 0


def cmd_sql(a) -> int:
    print(collect.gharchive_sql(a.ecosystem, date_from=getattr(a, "from"), date_to=a.to, limit=a.limit))
    return 0


def cmd_classify(a) -> int:
    patch = _read(a.patch) if a.patch else ""
    cls = signals.classify(a.ecosystem, title=a.title or "", body=a.body or "", patch=patch)
    print(json.dumps({
        "category": cls.category, "score": cls.score,
        "is_candidate": cls.is_candidate, "is_likely_fix": cls.is_likely_fix,
        "by_category": cls.by_category, "evidence": cls.evidence,
    }, indent=2, ensure_ascii=False))
    return 0


def _findings(rows) -> list[szz.Finding]:
    return [szz.Finding(**r) for r in rows]


def cmd_confirm(a) -> int:
    raw = json.loads(_read(a.candidate))
    cand = confirm.Candidate(
        id=raw["id"], ecosystem=raw["ecosystem"], title=raw.get("title", ""),
        body=raw.get("body", ""), patch=raw.get("patch", ""),
        before={k: _findings(v) for k, v in raw.get("before", {}).items()},
        after={k: _findings(v) for k, v in raw.get("after", {}).items()},
    )
    v = confirm.judge(cand, ownaudit_tool=a.ownaudit, baseline_tools=tuple(a.baseline))
    print(json.dumps(v.__dict__, indent=2, ensure_ascii=False))
    return 0


def cmd_metrics(a) -> int:
    rows = json.loads(_read(a.verdicts))
    verdicts = [confirm.Verdict(**r) for r in rows]
    rep = metrics.aggregate(verdicts, ownaudit_tool=a.ownaudit, baseline_tools=tuple(a.baseline))
    if a.markdown:
        print(metrics.render_markdown(rep))
    else:
        print(json.dumps(rep.as_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_sweep(a) -> int:
    pkgs = [sweep.Package(**p) for p in json.loads(_read(a.packages))]
    chosen = sweep.select_targets(pkgs, n=a.n, max_vetted_fraction=a.max_vetted)
    print(json.dumps([
        {"name": s.pkg.name, "registry": s.pkg.registry, "vetted": round(s.vetted, 3),
         "weight": round(s.weight, 3), "reason": s.reason}
        for s in chosen
    ], indent=2, ensure_ascii=False))
    return 0


def cmd_mine(a) -> int:
    token = a.token or os.environ.get("GITHUB_TOKEN", "")
    os.makedirs(a.out_dir, exist_ok=True)
    conn = schema.connect(a.store) if a.store else None
    res = mine.run(
        a.ecosystem, token=token, merged_after=a.merged_after or "",
        per_query=a.per_query, min_score=a.min_score, sleep=a.sleep, conn=conn,
    )
    if conn is not None:
        conn.commit()
    with open(os.path.join(a.out_dir, "dataset.json"), "w", encoding="utf-8") as f:
        json.dump(res.rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(res.summary_md())
    print(res.summary_md())
    return 0


def cmd_bq_sql(a) -> int:
    if a.kind == "gharchive":
        print(bigquery.gharchive_discovery_sql(
            a.ecosystem, date_from=getattr(a, "from"), date_to=a.to,
            max_changed_files=a.max_changed_files, limit=a.limit))
    else:
        print(bigquery.contents_sweep_sql(a.ecosystem, sample=not a.full, limit=a.limit))
    return 0


def cmd_bq_ingest(a) -> int:
    rows = bigquery.read_ndjson(_read(a.rows))
    os.makedirs(a.out_dir, exist_ok=True)
    conn = schema.connect(a.store) if a.store else None
    res = bigquery.ingest_rows(rows, a.ecosystem, min_meta_score=a.min_meta_score, conn=conn)
    if conn is not None:
        conn.commit()
    with open(os.path.join(a.out_dir, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(res.rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(res.summary_md())
    print(res.summary_md())
    return 0


def cmd_leadtime(a) -> int:
    lt = szz.lead_time(a.repo, a.sha, a.file, a.line)
    print(json.dumps(lt.__dict__, indent=2, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="leakmine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("queries", help="print GitHub-search query pack")
    q.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    q.add_argument("--merged-after", default="")
    q.set_defaults(fn=cmd_queries)

    s = sub.add_parser("sql", help="print GH-Archive BigQuery SQL")
    s.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    s.add_argument("--from", required=True, help="YYYYMMDD partition start")
    s.add_argument("--to", required=True, help="YYYYMMDD partition end")
    s.add_argument("--limit", type=int, default=2000)
    s.set_defaults(fn=cmd_sql)

    c = sub.add_parser("classify", help="patch-signal classify one candidate")
    c.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    c.add_argument("--patch", help="path to a unified diff")
    c.add_argument("--title", default="")
    c.add_argument("--body", default="")
    c.set_defaults(fn=cmd_classify)

    cf = sub.add_parser("confirm", help="judge a materialised candidate (before/after/patch)")
    cf.add_argument("--candidate", required=True)
    cf.add_argument("--ownaudit", default="ownaudit")
    cf.add_argument("--baseline", nargs="*", default=[])
    cf.set_defaults(fn=cmd_confirm)

    m = sub.add_parser("metrics", help="aggregate verdicts -> report")
    m.add_argument("--verdicts", required=True)
    m.add_argument("--ownaudit", default="ownaudit")
    m.add_argument("--baseline", nargs="*", default=[])
    m.add_argument("--markdown", action="store_true")
    m.set_defaults(fn=cmd_metrics)

    sw = sub.add_parser("sweep", help="select prospective sweep targets")
    sw.add_argument("--packages", required=True)
    sw.add_argument("--n", type=int, default=50)
    sw.add_argument("--max-vetted", type=float, default=0.3, dest="max_vetted")
    sw.set_defaults(fn=cmd_sweep)

    mn = sub.add_parser("mine", help="discover + classify a leak-fix corpus (CI-runnable)")
    mn.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    mn.add_argument("--merged-after", default="", help="ISO date YYYY-MM-DD; appends merged:>=")
    mn.add_argument("--per-query", type=int, default=50)
    mn.add_argument("--min-score", type=int, default=7)
    mn.add_argument("--sleep", type=float, default=1.0, help="throttle between API calls (s)")
    mn.add_argument("--out-dir", default="leakmine-out")
    mn.add_argument("--store", default="", help="SQLite path; empty = no DB written")
    mn.add_argument("--token", default="", help="GitHub token; falls back to $GITHUB_TOKEN")
    mn.set_defaults(fn=cmd_mine)

    bq = sub.add_parser("bq-sql", help="emit BigQuery SQL (GH-Archive discovery / contents sweep)")
    bq.add_argument("--kind", choices=("gharchive", "contents"), default="gharchive")
    bq.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    bq.add_argument("--from", default="20240101", help="YYYYMMDD partition start (gharchive)")
    bq.add_argument("--to", default="20241231", help="YYYYMMDD partition end (gharchive)")
    bq.add_argument("--max-changed-files", type=int, default=80, dest="max_changed_files")
    bq.add_argument("--full", action="store_true",
                    help="contents sweep: scan full ~2.7TB tables instead of sample_* (costs $$)")
    bq.add_argument("--limit", type=int, default=50000)
    bq.set_defaults(fn=cmd_bq_sql)

    bi = sub.add_parser("bq-ingest", help="ingest BigQuery NDJSON export -> store (metadata tier)")
    bi.add_argument("--rows", required=True, help="path to NDJSON exported from BigQuery")
    bi.add_argument("--ecosystem", required=True, choices=sorted(signals.ECOSYSTEMS))
    bi.add_argument("--min-meta-score", type=int, default=4, dest="min_meta_score")
    bi.add_argument("--out-dir", default="leakmine-out")
    bi.add_argument("--store", default="", help="SQLite path; empty = no DB written")
    bi.set_defaults(fn=cmd_bq_ingest)

    lt = sub.add_parser("leadtime", help="time-travel: commits between a leak and its human fix")
    lt.add_argument("--repo", required=True)
    lt.add_argument("--sha", required=True)
    lt.add_argument("--file", required=True)
    lt.add_argument("--line", type=int, required=True)
    lt.set_defaults(fn=cmd_leadtime)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
