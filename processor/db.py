"""Private SQLite storage owned exclusively by the Python processor.

Bronze retains exact response bodies and request provenance. Keyed match tables
support Silver processing; control tables track ingestion and rebuilds. Champion
identities are cached here for normalization and offline demo seeding.

Legacy aggregate tables remain for compatibility but are no longer refreshed or
served. The API reads a separate Gold-only SQLite snapshot published by gold.py.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import os
import sqlite3
from functools import wraps
from pathlib import Path

from filelock import FileLock

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "champions.db"
_locks: dict[str, FileLock] = {}


def writer_lock(database: Path | None = None) -> FileLock:
    path = (database or db_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return _locks.setdefault(str(path), FileLock(str(path) + ".pipeline.lock"))


def serialized_writer(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with writer_lock():
            return fn(*args, **kwargs)
    return wrapped


def db_path() -> Path:
    return Path(os.environ.get("CHAMPIONGG_DB", str(DEFAULT_DB_PATH)))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
-- -------------------------------------------------------------- bronze layer
CREATE TABLE IF NOT EXISTS bronze_fetch_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline     TEXT NOT NULL,
    parameters   TEXT NOT NULL DEFAULT '{}',
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    error        TEXT
);

-- Exact endpoint responses. Changed payloads are retained as new versions;
-- byte-identical responses for the same resource are deduplicated.
CREATE TABLE IF NOT EXISTS bronze_payloads (
    payload_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_run_id    INTEGER,
    source          TEXT NOT NULL,       -- riot-api | ddragon | riot-static
    dataset         TEXT NOT NULL,       -- e.g. match-v5.timeline
    routing_value   TEXT NOT NULL DEFAULT '',
    natural_key     TEXT NOT NULL,
    request_url     TEXT NOT NULL,
    request_params  TEXT NOT NULL DEFAULT '{}',
    response_json   TEXT NOT NULL,
    content_sha256  TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    FOREIGN KEY (fetch_run_id) REFERENCES bronze_fetch_runs(run_id),
    UNIQUE (source, dataset, routing_value, natural_key, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_bronze_payloads_lookup
    ON bronze_payloads (dataset, routing_value, natural_key, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_bronze_payloads_run
    ON bronze_payloads (fetch_run_id);

CREATE TABLE IF NOT EXISTS bronze_fetch_errors (
    error_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_run_id  INTEGER NOT NULL,
    dataset       TEXT NOT NULL,
    natural_key   TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    FOREIGN KEY (fetch_run_id) REFERENCES bronze_fetch_runs(run_id)
);

CREATE TABLE IF NOT EXISTS bronze_matches (
    match_id   TEXT PRIMARY KEY,
    json       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'riot',
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bronze_match_timelines (
    match_id   TEXT PRIMARY KEY,
    json       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'riot',
    fetched_at TEXT NOT NULL
);

-- Legacy landing table retained for a non-destructive migration.
CREATE TABLE IF NOT EXISTS raw_matches (
    match_id   TEXT PRIMARY KEY,           -- e.g. NA1_5187771234
    json       TEXT NOT NULL,              -- exact Match-V5 response body
    source     TEXT NOT NULL DEFAULT 'riot',  -- 'riot' | 'demo'
    fetched_at TEXT NOT NULL               -- ISO-8601 UTC
);

-- ------------------------------------------------------------ static cache
-- Champion identity from Data Dragon (no API key required).
CREATE TABLE IF NOT EXISTS champions (
    champion_id INTEGER PRIMARY KEY,       -- numeric key, e.g. 62
    key         TEXT NOT NULL,             -- ddragon id, e.g. "MonkeyKing"
    name        TEXT NOT NULL,             -- display name, e.g. "Wukong"
    title       TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]' -- JSON list, e.g. ["Fighter","Tank"]
);

-- ------------------------------------------------------- aggregate layer
CREATE TABLE IF NOT EXISTS patch_totals (
    patch   TEXT PRIMARY KEY,              -- e.g. "15.17"
    matches INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS champion_stats (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role        TEXT NOT NULL,             -- TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY
    games       INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    kills       INTEGER NOT NULL,
    deaths      INTEGER NOT NULL,
    assists     INTEGER NOT NULL,
    gold        INTEGER NOT NULL,
    damage      INTEGER NOT NULL,
    cs          INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id, role)
);

CREATE TABLE IF NOT EXISTS champion_bans (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    bans        INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id)
);

CREATE TABLE IF NOT EXISTS matchups (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role        TEXT NOT NULL,
    opponent_id INTEGER NOT NULL,          -- lane opponent (same role, enemy team)
    games       INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id, role, opponent_id)
);

CREATE TABLE IF NOT EXISTS builds (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role        TEXT NOT NULL,
    items       TEXT NOT NULL,             -- JSON list of first 3 completed item ids
    games       INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id, role, items)
);

CREATE TABLE IF NOT EXISTS spell_sets (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role        TEXT NOT NULL,
    spells      TEXT NOT NULL,             -- JSON [id, id] sorted
    games       INTEGER NOT NULL,
    wins       INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id, role, spells)
);

CREATE TABLE IF NOT EXISTS rune_sets (
    patch       TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role        TEXT NOT NULL,
    keystone    INTEGER NOT NULL,          -- perk id, e.g. 8010 Conqueror
    sub_style   INTEGER NOT NULL,          -- style id, e.g. 8400 Resolve
    games       INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    PRIMARY KEY (patch, champion_id, role, keystone, sub_style)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bronze_payload_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_id INTEGER NOT NULL REFERENCES bronze_payloads(payload_id),
            fetch_run_id INTEGER REFERENCES bronze_fetch_runs(run_id),
            observed_at TEXT NOT NULL,
            origin TEXT NOT NULL CHECK(origin IN ('fetch', 'legacy'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bronze_legacy_observation
            ON bronze_payload_observations(payload_id) WHERE origin='legacy';
        CREATE INDEX IF NOT EXISTS idx_bronze_observation_payload
            ON bronze_payload_observations(payload_id, observed_at);
        CREATE TABLE IF NOT EXISTS rebuild_runs (
            run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
            status TEXT NOT NULL, snapshot_path TEXT, report_json TEXT, error TEXT
        );
    """)
    conn.execute("""INSERT INTO bronze_payload_observations
        (payload_id, fetch_run_id, observed_at, origin)
        SELECT p.payload_id, p.fetch_run_id, p.fetched_at, 'legacy'
        FROM bronze_payloads p WHERE NOT EXISTS
        (SELECT 1 FROM bronze_payload_observations o WHERE o.payload_id=p.payload_id)""")
    conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES (1, ?)", (utcnow(),))
    conn.execute(
        """INSERT OR IGNORE INTO bronze_matches (match_id, json, source, fetched_at)
           SELECT match_id, json, source, fetched_at FROM raw_matches"""
    )
    conn.commit()


def store_bronze_payload(
    conn: sqlite3.Connection,
    *,
    source: str,
    dataset: str,
    natural_key: str,
    request_url: str,
    response_json: str,
    fetched_at: str,
    routing_value: str = "",
    request_params: str = "{}",
    fetch_run_id: int | None = None,
) -> bool:
    """Land an exact response body. Return True when it is a new version."""
    digest = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO bronze_payloads
           (fetch_run_id, source, dataset, routing_value, natural_key,
            request_url, request_params, response_json, content_sha256, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fetch_run_id, source, dataset, routing_value, natural_key,
         request_url, request_params, response_json, digest, fetched_at),
    )
    inserted = conn.total_changes > before
    payload_id = conn.execute("""SELECT payload_id FROM bronze_payloads
        WHERE source=? AND dataset=? AND routing_value=? AND natural_key=?
        AND content_sha256=?""", (source, dataset, routing_value, natural_key, digest)).fetchone()[0]
    conn.execute("""INSERT INTO bronze_payload_observations
        (payload_id, fetch_run_id, observed_at, origin) VALUES (?, ?, ?, 'fetch')""",
        (payload_id, fetch_run_id, fetched_at))
    return inserted


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def start_fetch_run(conn: sqlite3.Connection, pipeline: str, parameters: dict) -> int:
    cursor = conn.execute(
        "INSERT INTO bronze_fetch_runs (pipeline, parameters, started_at) VALUES (?, ?, ?)",
        (pipeline, json.dumps(parameters, sort_keys=True), utcnow()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_fetch_run(
    conn: sqlite3.Connection, run_id: int, *, status: str, error: str | None = None
) -> None:
    conn.execute(
        """UPDATE bronze_fetch_runs
           SET completed_at = ?, status = ?, error = ? WHERE run_id = ?""",
        (utcnow(), status, error, run_id),
    )
    conn.commit()


def record_fetch_error(
    conn: sqlite3.Connection,
    run_id: int,
    dataset: str,
    error: Exception | str,
    natural_key: str = "",
) -> None:
    conn.execute(
        """INSERT INTO bronze_fetch_errors
           (fetch_run_id, dataset, natural_key, error, occurred_at)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, dataset, natural_key, str(error), utcnow()),
    )


def open_db() -> sqlite3.Connection:
    conn = connect()
    init_schema(conn)
    return conn
