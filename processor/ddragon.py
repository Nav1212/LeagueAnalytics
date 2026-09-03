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

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPIONS_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"

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


def fetch_champion_list() -> tuple[str, list[tuple[int, str, str, str, list[str]]]]:
    """Return (ddragon_version, [(id, key, name, title, tags), ...]) from the CDN."""
    versions = requests.get(VERSIONS_URL, timeout=15).json()
    version = versions[0]
    data = requests.get(CHAMPIONS_URL.format(version=version), timeout=30).json()
    rows = []
    for key, champ in data["data"].items():
        rows.append((int(champ["key"]), key, champ["name"], champ.get("title", ""), champ.get("tags", [])))
    return version, rows


def sync_champions(conn: sqlite3.Connection) -> int:
    """Populate the `champions` table, preferring live Data Dragon data."""
    try:
        version, rows = fetch_champion_list()
        source = f"ddragon {version}"
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('ddragon_version', ?)", (version,)
        )
    except Exception as exc:  # offline fallback
        print(f"  ddragon unavailable ({exc}); using bundled fallback champion list")
        rows = [(cid, key, name, "", tags) for cid, key, name, tags in FALLBACK_CHAMPIONS]
        source = "bundled fallback"

    conn.executemany(
        "INSERT OR REPLACE INTO champions (champion_id, key, name, title, tags) VALUES (?, ?, ?, ?, ?)",
        [(cid, key, name, title, json.dumps(tags)) for cid, key, name, title, tags in rows],
    )
    conn.commit()
    print(f"  champions table: {len(rows)} champions ({source})")
    return len(rows)


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
