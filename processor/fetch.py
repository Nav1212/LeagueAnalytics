"""Lossless bronze ingestion for Riot's read-only League data sets.

Every successful source response is stored byte-for-byte in bronze before it
is parsed for discovery. Silver jobs can therefore be rebuilt independently.
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable

from . import db, ddragon
from .riot_api import RiotClient

QUEUE = "RANKED_SOLO_5x5"
RANKED_TIERS = ("DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON")
DIVISIONS = ("I", "II", "III", "IV")


def fetch_matches(
    max_matches: int = 500,
    players: int = 50,
    per_player: int = 20,
    platform: str = "na1",
    region: str = "americas",
    league_pages: int = 1,
    include_timelines: bool = True,
    include_player_data: bool = True,
    include_static: bool = True,
) -> int:
    """Pull the complete standard read-only LoL bronze set for one platform."""
    conn = db.open_db()
    parameters = {
        "max_matches": max_matches,
        "players": players,
        "per_player": per_player,
        "platform": platform,
        "region": region,
        "league_pages": league_pages,
        "include_timelines": include_timelines,
        "include_player_data": include_player_data,
        "include_static": include_static,
    }
    run_id = db.start_fetch_run(conn, "league-bronze", parameters)
    landed = errors = 0

    def record(
        dataset: str,
        routing_value: str,
        natural_key: str,
        url: str,
        raw: str,
        params: dict[str, Any],
    ) -> None:
        nonlocal landed
        if db.store_bronze_payload(
            conn,
            source="riot-api",
            dataset=dataset,
            routing_value=routing_value,
            natural_key=natural_key,
            request_url=url,
            request_params=json.dumps(params, sort_keys=True, separators=(",", ":")),
            response_json=raw,
            fetched_at=db.utcnow(),
            fetch_run_id=run_id,
        ):
            landed += 1
        if landed and landed % 25 == 0:
            conn.commit()

    def attempt(dataset: str, natural_key: str, action: Callable[[], Any]) -> Any | None:
        nonlocal errors
        try:
            return action()
        except Exception as exc:
            errors += 1
            db.record_fetch_error(conn, run_id, dataset, exc, natural_key)
            print(f"  {dataset} {natural_key}: {exc}")
            return None

    try:
        client = RiotClient(platform=platform, region=region, recorder=record)
        if include_static:
            print("fetching Data Dragon and Riot reference data...")
            static_result = ddragon.sync_all_static(
                conn, fetch_run_id=run_id, realm=ddragon.realm_for_platform(platform)
            )
            errors += int(static_result["errors"])

        print(f"fetching global League datasets for {platform}...")
        attempt("champion-v3.rotation", platform, client.champion_rotation)
        attempt("lol-status-v4.platform-data", platform, client.platform_status)
        attempt("lol-challenges-v1.config", platform, client.challenge_configs)
        attempt("lol-challenges-v1.percentiles", platform, client.challenge_percentiles)
        attempt("spectator-v5.featured-games", platform, client.featured_games)
        attempt("clash-v1.tournaments", platform, client.clash_tournaments)

        print(f"fetching ranked ladders for {platform}...")
        entries = attempt(
            "league-v4.apex-league", f"{platform}:{QUEUE}", client.top_ladder_entries
        ) or []
        for tier in RANKED_TIERS:
            for division in DIVISIONS:
                for page in range(1, league_pages + 1):
                    key = f"{QUEUE}:{tier}:{division}:{page}"
                    page_entries = attempt(
                        "league-v4.entries", key,
                        lambda t=tier, d=division, p=page: client.league_entries(
                            QUEUE, t, d, p
                        ),
                    )
                    if page_entries:
                        entries.extend(page_entries)
                    # Land the experimental representation as a distinct data
                    # set as well; silver can decide whether to consume it.
                    attempt(
                        "league-exp-v4.entries", key,
                        lambda t=tier, d=division, p=page: client.league_exp_entries(
                            QUEUE, t, d, p
                        ),
                    )

        by_puuid = {entry.get("puuid"): entry for entry in entries if entry.get("puuid")}
        player_entries = list(by_puuid.values())
        random.shuffle(player_entries)
        player_entries = player_entries[:players]
        print(f"  {len(entries)} entries, {len(player_entries)} sampled players")

        match_ids: list[str] = []
        for entry in player_entries:
            puuid = str(entry["puuid"])
            if include_player_data:
                attempt("account-v1.account", puuid, lambda p=puuid: client.account_by_puuid(p))
                attempt("summoner-v4.summoner", puuid, lambda p=puuid: client.summoner_by_puuid(p))
                attempt(
                    "champion-mastery-v4.masteries", puuid,
                    lambda p=puuid: client.champion_masteries(p),
                )
                attempt(
                    "champion-mastery-v4.score", puuid,
                    lambda p=puuid: client.champion_mastery_score(p),
                )
                attempt(
                    "lol-challenges-v1.player-data", puuid,
                    lambda p=puuid: client.player_challenges(p),
                )
                attempt("spectator-v5.active-game", puuid, lambda p=puuid: client.active_game(p))

            ids = attempt(
                "match-v5.match-ids", puuid,
                lambda p=puuid: client.match_ids_by_puuid(p, count=per_player),
            ) or []
            for match_id in ids:
                if match_id not in match_ids:
                    match_ids.append(match_id)
                if len(match_ids) >= max_matches:
                    break
            if len(match_ids) >= max_matches:
                break

        have_matches = {
            row["match_id"] for row in conn.execute("SELECT match_id FROM bronze_matches")
        }
        have_timelines = {
            row["match_id"]
            for row in conn.execute("SELECT match_id FROM bronze_match_timelines")
        }
        new_matches = [match_id for match_id in match_ids if match_id not in have_matches]
        new_timelines = (
            [match_id for match_id in match_ids if match_id not in have_timelines]
            if include_timelines else []
        )
        print(
            f"  {len(match_ids)} discovered; {len(new_matches)} matches and "
            f"{len(new_timelines)} timelines to fetch"
        )

        stored = 0
        for index, match_id in enumerate(match_ids, 1):
            if match_id in new_matches:
                result = attempt("match-v5.match", match_id, lambda m=match_id: client.match(m))
                if result is not None:
                    raw_text, _parsed = result
                    conn.execute(
                        """INSERT OR IGNORE INTO bronze_matches
                           (match_id, json, source, fetched_at) VALUES (?, ?, 'riot', ?)""",
                        (match_id, raw_text, db.utcnow()),
                    )
                    stored += 1
            if match_id in new_timelines:
                timeline = attempt(
                    "match-v5.timeline", match_id,
                    lambda m=match_id: client.timeline(m),
                )
                if timeline is not None:
                    raw_timeline, _parsed = timeline
                    conn.execute(
                        """INSERT OR IGNORE INTO bronze_match_timelines
                           (match_id, json, source, fetched_at) VALUES (?, ?, 'riot', ?)""",
                        (match_id, raw_timeline, db.utcnow()),
                    )
            if index % 25 == 0:
                conn.commit()
                print(f"    {index}/{len(match_ids)} processed")

        conn.commit()
        status = "complete" if errors == 0 else "partial"
        db.finish_fetch_run(conn, run_id, status=status)
        print(
            f"done: {stored} matches stored; {landed} new bronze payload versions; "
            f"{errors} request errors"
        )
        return stored
    except Exception as exc:
        db.finish_fetch_run(conn, run_id, status="failed", error=str(exc))
        raise
    finally:
        conn.close()
