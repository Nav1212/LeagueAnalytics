"""The public serving contract and atomic publication of Gold-only SQLite files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

import duckdb
from filelock import FileLock

from . import db

SCHEMA_VERSION = 1
# This allowlist is also the schema used by integration fixtures and documentation.
TABLES = {
    "patch_totals": ("source TEXT NOT NULL, patch TEXT NOT NULL, matches INTEGER NOT NULL", ("source", "patch")),
    "champion_stats": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, role TEXT NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL, kills INTEGER NOT NULL, deaths INTEGER NOT NULL, assists INTEGER NOT NULL, gold INTEGER NOT NULL, damage INTEGER NOT NULL, cs INTEGER NOT NULL", ("source", "patch", "champion_id", "role")),
    "champion_bans": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, bans INTEGER NOT NULL", ("source", "patch", "champion_id")),
    "matchups": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, role TEXT NOT NULL, opponent_id INTEGER NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL", ("source", "patch", "champion_id", "role", "opponent_id")),
    "builds": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, role TEXT NOT NULL, items TEXT NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL", ("source", "patch", "champion_id", "role", "items")),
    "spell_sets": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, role TEXT NOT NULL, spells TEXT NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL", ("source", "patch", "champion_id", "role", "spells")),
    "rune_sets": ("source TEXT NOT NULL, patch TEXT NOT NULL, champion_id INTEGER NOT NULL, role TEXT NOT NULL, keystone INTEGER NOT NULL, sub_style INTEGER NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL", ("source", "patch", "champion_id", "role", "keystone", "sub_style")),
    "champions": ("champion_id INTEGER NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL, title TEXT NOT NULL, tags TEXT NOT NULL", ("champion_id",)),
    "source_counts": ("source TEXT NOT NULL, raw_matches INTEGER NOT NULL", ("source",)),
    "rune_catalog": ("version TEXT NOT NULL, locale TEXT NOT NULL, styles TEXT NOT NULL", ("version", "locale")),
    "meta": ("key TEXT NOT NULL, value TEXT NOT NULL", ("key",)),
}
SERVING_KEYS = {name: key for name, (_, key) in TABLES.items()}
SCHEMA = "\n".join(
    f"CREATE TABLE gold_{name} ({columns}, PRIMARY KEY ({','.join(key)}));"
    for name, (columns, key) in TABLES.items()
)


def gold_dir() -> Path:
    configured = Path(os.environ.get("CHAMPIONGG_GOLD_DIR", "data/gold"))
    return configured if configured.is_absolute() else db.REPO_ROOT / configured


def init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def publish(analytics: Path, run_id: str, output_dir: Path | None = None) -> dict:
    """Copy only the public contract; never copy pages from the private database."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Invalid publication run ID")
    output = (output_dir or gold_dir()).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output / ".publish.lock")):
        snapshot = output / f"gold-{run_id}.sqlite"
        if snapshot.exists():
            raise FileExistsError(f"Snapshot already exists: {snapshot.name}")
        token = uuid.uuid4().hex
        temporary = output / f".gold-{token}.tmp"
        manifest_temp = output / f".current-{token}.tmp"
        previous = None
        try:
            previous = json.loads((output / "current.json").read_text(encoding="utf-8")).get("snapshot")
        except (OSError, ValueError, AttributeError):
            pass
        source = duckdb.connect(str(analytics), read_only=True)
        target = sqlite3.connect(temporary)
        try:
            target.execute("PRAGMA journal_mode=DELETE")
            target.execute("PRAGMA synchronous=FULL")
            init_schema(target)
            with target:
                for name in TABLES:
                    table = f"gold_{name}"
                    columns = [row[1] for row in target.execute(f"PRAGMA table_info({table})")]
                    where = " WHERE key='ddragon_version'" if name == "meta" else ""
                    cursor = source.execute(f"SELECT {','.join(columns)} FROM {table}{where}")
                    while batch := cursor.fetchmany(5000):
                        target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in columns)})", batch)
                published_at = db.utcnow()
                target.executemany("INSERT OR REPLACE INTO gold_meta VALUES (?, ?)", [
                    ("schema_version", str(SCHEMA_VERSION)), ("run_id", run_id),
                    ("aggregated_at", published_at),
                ])
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Gold snapshot integrity check failed")
        except BaseException:
            target.close()
            temporary.unlink(missing_ok=True)
            raise
        finally:
            target.close()
            source.close()
            # Failed candidates are harmless and must never become current.
        try:
            os.replace(temporary, snapshot)
            manifest = {"snapshot": snapshot.name, "schemaVersion": SCHEMA_VERSION,
                        "runId": run_id, "publishedAt": published_at}
            with manifest_temp.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(manifest_temp, output / "current.json")
            # The manifest is the publication commit point. Cleanup is best effort.
            for candidate in output.glob("gold-*.sqlite"):
                if candidate.name not in (snapshot.name, previous):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass  # Windows readers can keep older snapshots open.
            return manifest
        finally:
            temporary.unlink(missing_ok=True)
            manifest_temp.unlink(missing_ok=True)
