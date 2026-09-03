"""Fetch ranked matches from the Riot API into the raw layer.

The raw layer mirrors the API *exactly*: for every match we store the
unmodified response body string in `raw_matches.json`. Aggregation is a
separate, repeatable step (see aggregate.py).

Strategy (standard for sites like champion.gg):
  1. Pull the top ladder (challenger/GM/master) for the configured platform.
  2. For each player's puuid, list their recent ranked-solo match ids.
  3. Fetch each match not already stored and insert the raw body.
"""

from __future__ import annotations

import datetime as dt
import random

from . import db
from .riot_api import RiotClient


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def fetch_matches(
    max_matches: int = 500,
    players: int = 50,
    per_player: int = 20,
    platform: str = "na1",
    region: str = "americas",
) -> int:
    conn = db.open_db()
    client = RiotClient(platform=platform, region=region)

    print(f"fetching top ladder for {platform}...")
    entries = client.top_ladder_entries()
    random.shuffle(entries)
    print(f"  {len(entries)} ladder players found")

    have = {r["match_id"] for r in conn.execute("SELECT match_id FROM raw_matches")}
    print(f"  {len(have)} matches already stored")

    todo: list[str] = []
    for entry in entries[:players]:
        puuid = entry.get("puuid")
        if not puuid:
            continue
        try:
            ids = client.match_ids_by_puuid(puuid, count=per_player)
        except Exception as exc:
            print(f"    skipping player: {exc}")
            continue
        todo.extend(m for m in ids if m not in have and m not in todo)
        if len(todo) >= max_matches:
            break

    todo = todo[:max_matches]
    print(f"  {len(todo)} new matches to fetch")

    stored = 0
    for i, match_id in enumerate(todo, 1):
        try:
            raw_text, _parsed = client.match(match_id)
        except Exception as exc:
            print(f"    {match_id}: {exc}")
            continue
        conn.execute(
            "INSERT OR IGNORE INTO raw_matches (match_id, json, source, fetched_at) VALUES (?, ?, 'riot', ?)",
            (match_id, raw_text, utcnow()),
        )
        stored += 1
        if i % 25 == 0:
            conn.commit()
            print(f"    {i}/{len(todo)} fetched")
    conn.commit()
    conn.close()
    print(f"done: {stored} raw matches stored")
    return stored
