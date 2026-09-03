"""SQLite database layer shared by the processor and (by convention) the server.

Two layers of tables:

1. Raw layer — `raw_matches` stores the *exact* JSON body returned by the Riot
   Match-V5 API, byte-for-byte as received. No reshaping, no field selection.
   All modeling is derived from this layer and can be rebuilt at any time.

2. Aggregate layer — simple per-patch/per-role rollups (win rate, pick rate,
   ban rate, matchups, item builds, spells, runes) that the web server reads.
   These are intentionally basic; more complex modeling comes later and will
   also be derived from the raw layer.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "champions.db"


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
-- ---------------------------------------------------------------- raw layer
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
    conn.commit()


def open_db() -> sqlite3.Connection:
    conn = connect()
    init_schema(conn)
    return conn
