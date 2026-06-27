"""The mining store — a single SQLite file holding the whole pipeline's state.

Five tables (docs/leakfix-mine.md §2): candidates -> patches -> labels -> tool_runs ->
verdicts. SQLite over DuckDB so it's stdlib-only and the CI smoke needs nothing installed.
Findings and verdicts are stored as JSON text blobs (they're nested) — the relational part
is just the spine that lets you resume a run and join across stages.
"""
from __future__ import annotations

import json
import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS candidates (
  id          TEXT PRIMARY KEY,
  ecosystem   TEXT,
  query       TEXT,
  repo        TEXT,
  number      INTEGER,
  kind        TEXT,          -- pr | issue
  title       TEXT,
  body        TEXT,
  state       TEXT,
  merged      INTEGER,
  url         TEXT
);

CREATE TABLE IF NOT EXISTS patches (
  candidate_id TEXT REFERENCES candidates(id),
  base_sha     TEXT,
  head_sha     TEXT,
  files_json   TEXT,
  diff_text    TEXT
);

CREATE TABLE IF NOT EXISTS labels (
  candidate_id TEXT REFERENCES candidates(id),
  label        TEXT,         -- category from signals
  score        INTEGER,
  evidence     TEXT,
  classifier   TEXT          -- keyword | patch | llm | manual
);

CREATE TABLE IF NOT EXISTS tool_runs (
  candidate_id   TEXT REFERENCES candidates(id),
  tool           TEXT,
  version        TEXT,
  before_json    TEXT,       -- list[Finding] on the pre-fix revision
  after_json     TEXT,       -- list[Finding] on the post-fix revision
  status         TEXT,
  runtime_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS verdicts (
  -- one final verdict per candidate; resume/re-confirm must upsert, not append.
  candidate_id      TEXT PRIMARY KEY REFERENCES candidates(id),
  is_real_fix       INTEGER,
  category          TEXT,
  unique_to_own     INTEGER,
  caught_by         TEXT,    -- json list
  missed_by         TEXT,    -- json list
  own_resolution    TEXT,
  notes             TEXT     -- json list
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    # SQLite leaves FK enforcement OFF by default, so the REFERENCES clauses are inert
    # until enabled — and it must be enabled per connection, before any DML.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    return conn


def insert_candidate(conn: sqlite3.Connection, c: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO candidates "
        "(id,ecosystem,query,repo,number,kind,title,body,state,merged,url) "
        "VALUES (:id,:ecosystem,:query,:repo,:number,:kind,:title,:body,:state,:merged,:url)",
        {**{k: None for k in (
            "id", "ecosystem", "query", "repo", "number", "kind",
            "title", "body", "state", "merged", "url")}, **c},
    )


def insert_label(conn: sqlite3.Connection, candidate_id: str, label: str, score: int,
                 evidence: list[str], classifier: str) -> None:
    conn.execute(
        "INSERT INTO labels (candidate_id,label,score,evidence,classifier) VALUES (?,?,?,?,?)",
        (candidate_id, label, score, json.dumps(evidence), classifier),
    )


def insert_verdict(conn: sqlite3.Connection, v) -> None:
    # upsert: re-confirming a candidate replaces its verdict rather than duplicating it.
    conn.execute(
        "INSERT OR REPLACE INTO verdicts "
        "(candidate_id,is_real_fix,category,unique_to_own,caught_by,missed_by,own_resolution,notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (v.candidate_id, int(v.is_real_fix), v.category, int(v.unique_to_ownaudit),
         json.dumps(v.caught_by), json.dumps(v.missed_by), v.own_resolution, json.dumps(v.notes)),
    )


def count(conn: sqlite3.Connection, table: str) -> int:
    # table name is from a fixed internal set, never user input.
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
