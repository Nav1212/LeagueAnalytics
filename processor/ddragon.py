"""Data Dragon client: champion identity data (numeric id <-> key <-> name).

Data Dragon is Riot's static-data CDN and requires no API key. We cache the
champion list into the `champions` table so the rest of the pipeline (and the
web server) never needs the network. If the network is unavailable, we fall
back to a bundled snapshot of well-known champions.
"""

from __future__ import annotations

import json
import sqlite3

import requests

from . import db

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPIONS_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
LANGUAGES_URL = "https://ddragon.leagueoflegends.com/cdn/languages.json"
REALM_URL = "https://ddragon.leagueoflegends.com/realms/{realm}.json"
RIOT_STATIC_BASE = "https://static.developer.riotgames.com/docs/lol"
PLATFORM_REALMS = {
    "br1": "br", "eun1": "eune", "euw1": "euw", "jp1": "jp", "kr": "kr",
    "la1": "lan", "la2": "las", "na1": "na", "oc1": "oce", "ru": "ru", "tr1": "tr",
    "ph2": "ph", "sg2": "sg", "th2": "th", "tw2": "tw", "vn2": "vn",
}


def realm_for_platform(platform: str) -> str:
    return PLATFORM_REALMS.get(platform.lower(), platform.lower())

# Fallback snapshot: (numeric id, ddragon key, display name, tags)
# Used only when Data Dragon is unreachable.
FALLBACK_CHAMPIONS = [
    (266, "Aatrox", "Aatrox", ["Fighter", "Tank"]),
    (103, "Ahri", "Ahri", ["Mage", "Assassin"]),
    (84, "Akali", "Akali", ["Assassin"]),
    (12, "Alistar", "Alistar", ["Tank", "Support"]),
    (32, "Amumu", "Amumu", ["Tank", "Mage"]),
    (22, "Ashe", "Ashe", ["Marksman", "Support"]),
    (53, "Blitzcrank", "Blitzcrank", ["Tank", "Support"]),
    (201, "Braum", "Braum", ["Support", "Tank"]),
    (51, "Caitlyn", "Caitlyn", ["Marksman"]),
    (164, "Camille", "Camille", ["Fighter", "Tank"]),
    (122, "Darius", "Darius", ["Fighter", "Tank"]),
    (131, "Diana", "Diana", ["Fighter", "Assassin"]),
    (119, "Draven", "Draven", ["Marksman"]),
    (245, "Ekko", "Ekko", ["Assassin", "Fighter"]),
    (60, "Elise", "Elise", ["Mage", "Fighter"]),
    (81, "Ezreal", "Ezreal", ["Marksman", "Mage"]),
    (114, "Fiora", "Fiora", ["Fighter", "Assassin"]),
    (86, "Garen", "Garen", ["Fighter", "Tank"]),
    (104, "Graves", "Graves", ["Marksman"]),
    (120, "Hecarim", "Hecarim", ["Fighter", "Tank"]),
    (39, "Irelia", "Irelia", ["Fighter", "Assassin"]),
    (40, "Janna", "Janna", ["Support", "Mage"]),
    (59, "JarvanIV", "Jarvan IV", ["Tank", "Fighter"]),
    (24, "Jax", "Jax", ["Fighter", "Assassin"]),
    (202, "Jhin", "Jhin", ["Marksman", "Mage"]),
    (222, "Jinx", "Jinx", ["Marksman"]),
    (145, "Kaisa", "Kai'Sa", ["Marksman"]),
    (30, "Karthus", "Karthus", ["Mage"]),
    (55, "Katarina", "Katarina", ["Assassin", "Mage"]),
    (141, "Kayn", "Kayn", ["Fighter", "Assassin"]),
    (121, "Khazix", "Kha'Zix", ["Assassin"]),
    (64, "LeeSin", "Lee Sin", ["Fighter", "Assassin"]),
    (89, "Leona", "Leona", ["Tank", "Support"]),
    (236, "Lucian", "Lucian", ["Marksman"]),
    (117, "Lulu", "Lulu", ["Support", "Mage"]),
    (99, "Lux", "Lux", ["Mage", "Support"]),
    (54, "Malphite", "Malphite", ["Tank", "Fighter"]),
    (11, "MasterYi", "Master Yi", ["Assassin", "Fighter"]),
    (21, "MissFortune", "Miss Fortune", ["Marksman"]),
    (82, "Mordekaiser", "Mordekaiser", ["Fighter"]),
    (25, "Morgana", "Morgana", ["Mage", "Support"]),
    (267, "Nami", "Nami", ["Support", "Mage"]),
    (75, "Nasus", "Nasus", ["Fighter", "Tank"]),
    (111, "Nautilus", "Nautilus", ["Tank", "Support"]),
    (61, "Orianna", "Orianna", ["Mage", "Support"]),
    (516, "Ornn", "Ornn", ["Tank", "Fighter"]),
    (80, "Pantheon", "Pantheon", ["Fighter", "Assassin"]),
    (555, "Pyke", "Pyke", ["Support", "Assassin"]),
    (497, "Rakan", "Rakan", ["Support"]),
    (58, "Renekton", "Renekton", ["Fighter", "Tank"]),
    (92, "Riven", "Riven", ["Fighter", "Assassin"]),
    (13, "Ryze", "Ryze", ["Mage", "Fighter"]),
    (113, "Sejuani", "Sejuani", ["Tank", "Fighter"]),
    (235, "Senna", "Senna", ["Marksman", "Support"]),
    (875, "Sett", "Sett", ["Fighter", "Tank"]),
    (98, "Shen", "Shen", ["Tank"]),
    (14, "Sion", "Sion", ["Tank", "Fighter"]),
    (37, "Sona", "Sona", ["Support", "Mage"]),
    (16, "Soraka", "Soraka", ["Support", "Mage"]),
    (517, "Sylas", "Sylas", ["Mage", "Assassin"]),
    (134, "Syndra", "Syndra", ["Mage"]),
    (91, "Talon", "Talon", ["Assassin"]),
    (412, "Thresh", "Thresh", ["Support", "Fighter"]),
    (18, "Tristana", "Tristana", ["Marksman", "Assassin"]),
    (29, "Twitch", "Twitch", ["Marksman", "Assassin"]),
    (110, "Varus", "Varus", ["Marksman", "Mage"]),
    (67, "Vayne", "Vayne", ["Marksman", "Assassin"]),
    (254, "Vi", "Vi", ["Fighter", "Assassin"]),
    (112, "Viktor", "Viktor", ["Mage"]),
    (8, "Vladimir", "Vladimir", ["Mage"]),
    (106, "Volibear", "Volibear", ["Fighter", "Tank"]),
    (19, "Warwick", "Warwick", ["Fighter", "Tank"]),
    (62, "MonkeyKing", "Wukong", ["Fighter", "Tank"]),
    (498, "Xayah", "Xayah", ["Marksman"]),
    (5, "XinZhao", "Xin Zhao", ["Fighter", "Assassin"]),
    (157, "Yasuo", "Yasuo", ["Fighter", "Assassin"]),
    (777, "Yone", "Yone", ["Assassin", "Fighter"]),
    (350, "Yuumi", "Yuumi", ["Support", "Mage"]),
    (154, "Zac", "Zac", ["Tank", "Fighter"]),
    (238, "Zed", "Zed", ["Assassin"]),
    (26, "Zilean", "Zilean", ["Support", "Mage"]),
    (142, "Zoe", "Zoe", ["Mage", "Support"]),
    (143, "Zyra", "Zyra", ["Mage", "Support"]),
]


class StaticLoader:
    """One download path for demo/static ingestion, with exact Bronze recording."""
    def __init__(self, conn: sqlite3.Connection, fetch_run_id: int | None = None):
        self.conn = conn
        self.fetch_run_id = fetch_run_id
        self.stored = 0
        self.errors = 0

    def fetch(self, source: str, dataset: str, natural_key: str, url: str,
              routing: str = "") -> tuple[str, object] | None:
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            raw = response.text
            if db.store_bronze_payload(
                self.conn, source=source, dataset=dataset, natural_key=natural_key,
                routing_value=routing, request_url=url, response_json=raw,
                fetched_at=db.utcnow(), fetch_run_id=self.fetch_run_id,
            ):
                self.stored += 1
            return raw, response.json()
        except Exception as exc:
            self.errors += 1
            if self.fetch_run_id is not None:
                db.record_fetch_error(self.conn, self.fetch_run_id, dataset, exc, natural_key)
            print(f"  {dataset} unavailable ({exc})")
            return None


def sync_champions(conn: sqlite3.Connection) -> int:
    """Seed UI static data through the same recorded loader as full ingestion."""
    run_id = db.start_fetch_run(conn, "demo-static", {"locale": "en_US"})
    loader = StaticLoader(conn, run_id)
    try:
        versions = loader.fetch("ddragon", "ddragon.versions", "all", VERSIONS_URL)
        champions = None
        if versions and versions[1]:
            version = str(versions[1][0])
            champions = loader.fetch("ddragon", "ddragon.champion-summary", f"{version}:en_US",
                                     CHAMPIONS_URL.format(version=version), version)
            loader.fetch("ddragon", "ddragon.runes", f"{version}:en_US",
                         f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json", version)
            if champions:
                conn.execute("INSERT OR REPLACE INTO meta VALUES ('ddragon_version', ?)", (version,))
        if champions:
            rows = [(int(c["key"]), key, c["name"], c.get("title", ""), json.dumps(c.get("tags", [])))
                    for key, c in champions[1]["data"].items()]
            conn.executemany("INSERT OR REPLACE INTO champions VALUES (?, ?, ?, ?, ?)", rows)
        elif not conn.execute("SELECT 1 FROM champions LIMIT 1").fetchone():
            conn.executemany("INSERT INTO champions VALUES (?, ?, ?, ?, ?)",
                             [(cid, key, name, "", json.dumps(tags)) for cid, key, name, tags in FALLBACK_CHAMPIONS])
        db.finish_fetch_run(conn, run_id, status="partial" if loader.errors else "complete")
        return conn.execute("SELECT count(*) FROM champions").fetchone()[0]
    except Exception as exc:
        db.finish_fetch_run(conn, run_id, status="failed", error=str(exc))
        raise


def load_champions(conn: sqlite3.Connection) -> dict[int, dict]:
    """id -> {key, name, title, tags} from the local cache (syncing if empty)."""
    rows = conn.execute("SELECT * FROM champions").fetchall()
    if not rows:
        sync_champions(conn)
        rows = conn.execute("SELECT * FROM champions").fetchall()
    return {
        r["champion_id"]: {
            "key": r["key"],
            "name": r["name"],
            "title": r["title"],
            "tags": json.loads(r["tags"]),
        }
        for r in rows
    }


def sync_all_static(
    conn: sqlite3.Connection,
    *,
    fetch_run_id: int | None = None,
    locale: str = "en_US",
    realm: str = "na",
    champion_details: bool = True,
) -> dict[str, int | str]:
    """Land Riot's LoL static datasets byte-for-byte and refresh identities."""
    loader = StaticLoader(conn, fetch_run_id)
    fetch_and_land = loader.fetch

    versions_result = fetch_and_land(
        "ddragon", "ddragon.versions", "all", VERSIONS_URL
    )
    if versions_result is None:
        return {"version": "unknown", "stored": loader.stored, "errors": loader.errors}
    versions = versions_result[1]
    version = str(versions[0])

    fetch_and_land("ddragon", "ddragon.languages", "all", LANGUAGES_URL)
    fetch_and_land(
        "ddragon", "ddragon.realm", realm, REALM_URL.format(realm=realm), realm
    )

    data_urls = {
        "ddragon.champion-summary": "champion.json",
        "ddragon.items": "item.json",
        "ddragon.summoner-spells": "summoner.json",
        "ddragon.runes": "runesReforged.json",
        "ddragon.profile-icons": "profileicon.json",
        "ddragon.maps": "map.json",
    }
    results: dict[str, tuple[str, object] | None] = {}
    for dataset, filename in data_urls.items():
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/{filename}"
        results[dataset] = fetch_and_land(
            "ddragon", dataset, f"{version}:{locale}", url, version
        )

    champion_result = results["ddragon.champion-summary"]
    if champion_result is not None:
        champion_data = champion_result[1]["data"]
        rows = [
            (
                int(champ["key"]), key, champ["name"], champ.get("title", ""),
                json.dumps(champ.get("tags", [])),
            )
            for key, champ in champion_data.items()
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO champions
               (champion_id, key, name, title, tags) VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        if champion_details:
            for key in champion_data:
                url = (
                    f"https://ddragon.leagueoflegends.com/cdn/{version}/data/"
                    f"{locale}/champion/{key}.json"
                )
                fetch_and_land(
                    "ddragon", "ddragon.champion-detail",
                    f"{version}:{locale}:{key}", url, version,
                )

    reference_files = {
        "riot-static.seasons": "seasons.json",
        "riot-static.queues": "queues.json",
        "riot-static.maps": "maps.json",
        "riot-static.game-modes": "gameModes.json",
        "riot-static.game-types": "gameTypes.json",
    }
    for dataset, filename in reference_files.items():
        fetch_and_land(
            "riot-static", dataset, "all", f"{RIOT_STATIC_BASE}/{filename}"
        )

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('ddragon_version', ?)",
        (version,),
    )
    conn.commit()
    return {"version": version, "stored": loader.stored, "errors": loader.errors}
