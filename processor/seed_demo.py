"""Seed the raw layer with realistic demo matches (no API key required).

Generates synthetic matches in the *exact* Match-V5 response shape (a faithful
subset of its fields) and stores them in `raw_matches` with source='demo', so
the whole pipeline — raw layer -> aggregation -> server -> frontend — can be
exercised before a RIOT_API_KEY is available. Champions get stable hidden
strength/popularity values so win/pick/ban rates, matchups and builds look
plausible rather than uniform.

Swap in real data later with `python -m processor.main fetch` and re-run
`aggregate`; demo rows can be purged with `python -m processor.main purge-demo`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random

from . import db, ddragon

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
PATCHES = ["16.16", "16.17"]  # oldest -> latest
LATEST_SHARE = 0.65           # share of games on the latest patch

# ---------------------------------------------------------------- item pools
BOOTS = {"Marksman": 3006, "Mage": 3020, "Assassin": 3158, "Fighter": 3111,
         "Tank": 3047, "Support": 3158}
ITEM_POOLS = {
    "Marksman": [3031, 6672, 6673, 3046, 3094, 3072, 3036, 3033, 6675, 3508, 3153],
    "Mage":     [6653, 6655, 3089, 3157, 3135, 4645, 3116, 6657, 3102, 4628, 3040],
    "Assassin": [6676, 3142, 6695, 6698, 6697, 3814, 3156, 6694, 3071],
    "Fighter":  [3078, 3071, 3161, 6333, 3053, 3748, 3074, 6610, 3156],
    "Tank":     [3068, 3075, 3065, 3110, 3742, 3143, 3083, 3001, 2502],
    "Support":  [6617, 3504, 6616, 3222, 3107, 3190, 2065, 3050],
}
TRINKETS = [3340, 3363, 3364]

# ------------------------------------------------------------- spells / runes
SPELLS_BY_ROLE = {
    "TOP":     [(4, 12), (4, 14), (4, 6)],
    "JUNGLE":  [(4, 11)],
    "MIDDLE":  [(4, 14), (4, 12), (4, 21), (4, 1)],
    "BOTTOM":  [(4, 7), (4, 1), (4, 21)],
    "UTILITY": [(4, 14), (4, 3), (4, 1)],
}
RUNES = {  # class -> (primary style, [keystones], [sub styles])
    "Marksman": (8000, [8005, 8021, 8008], [8200, 8100, 8300]),
    "Mage":     (8200, [8229, 8214, 8112, 8369], [8300, 8100, 8400]),
    "Assassin": (8100, [8112, 8128, 9923], [8000, 8200]),
    "Fighter":  (8000, [8010, 8437, 8008], [8400, 8000, 8300]),
    "Tank":     (8400, [8437, 8439, 8465], [8000, 8300, 8200]),
    "Support":  (8200, [8214, 8465, 8439], [8300, 8400]),
}
FILLER_PERKS = {8000: [9111, 9104, 8014], 8100: [8139, 8138, 8135], 8200: [8226, 8210, 8237],
                8300: [8304, 8345, 8347], 8400: [8401, 8444, 8451]}


def _h(s: str) -> float:
    """Stable uniform [0,1) from a string."""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def champion_class(tags: list[str]) -> str:
    for tag in tags:
        if tag in ITEM_POOLS:
            return tag
    return "Fighter"


def roles_for(champ_id: int, info: dict) -> list[str]:
    """Plausible role(s) from ddragon tags, deterministic per champion."""
    tags = info["tags"] or ["Fighter"]
    primary, secondary = tags[0], (tags[1] if len(tags) > 1 else tags[0])
    options = {
        "Marksman": ["BOTTOM"],
        "Support": ["UTILITY"],
        "Mage": ["MIDDLE", "UTILITY" if secondary == "Support" else "MIDDLE"],
        "Assassin": ["MIDDLE", "JUNGLE"],
        "Fighter": ["TOP", "JUNGLE"],
        "Tank": ["TOP", "JUNGLE", "UTILITY"],
    }[primary if primary in ITEM_POOLS else "Fighter"]
    r = _h(f"role:{champ_id}")
    main = options[int(r * len(options)) % len(options)]
    roles = [main]
    if _h(f"role2:{champ_id}") < 0.35:  # some champions flex a second role
        alt = options[(int(r * len(options)) + 1) % len(options)]
        if alt != main:
            roles.append(alt)
    return roles


class DemoWorld:
    """Hidden per-champion parameters that drive the synthetic results."""

    def __init__(self, champions: dict[int, dict]):
        self.champions = champions
        self.pools: dict[str, list[int]] = {r: [] for r in ROLES}
        self.role_of: dict[int, list[str]] = {}
        self.wr: dict[tuple[int, str], float] = {}      # (champ, patch) -> base winrate
        self.pop: dict[int, float] = {}                  # popularity weight
        for cid, info in champions.items():
            rs = roles_for(cid, info)
            self.role_of[cid] = rs
            for role in rs:
                self.pools[role].append(cid)
            base = 0.44 + 0.12 * _h(f"wr:{cid}")
            for patch in PATCHES:
                delta = (_h(f"patch:{patch}:{cid}") - 0.5) * 0.04
                self.wr[(cid, patch)] = min(0.60, max(0.40, base + delta))
            self.pop[cid] = math.exp(2.2 * _h(f"pop:{cid}"))

    def pick(self, rng: random.Random, role: str, taken: set[int]) -> int:
        pool = [c for c in self.pools[role] if c not in taken]
        weights = [self.pop[c] for c in pool]
        return rng.choices(pool, weights=weights)[0]

    def ban_weights(self, patch: str) -> tuple[list[int], list[float]]:
        ids = list(self.champions)
        return ids, [self.pop[c] * math.exp((self.wr[(c, patch)] - 0.5) * 22) for c in ids]


def _participant(rng: random.Random, world: DemoWorld, cid: int, role: str,
                 team_id: int, win: bool, pid: int, duration: int) -> dict:
    info = world.champions[cid]
    cls = champion_class(info["tags"])
    minutes = duration / 60

    kda_mult = rng.uniform(1.15, 1.55) if win else rng.uniform(0.55, 0.95)
    base_k = {"TOP": 4.5, "JUNGLE": 5.5, "MIDDLE": 6.0, "BOTTOM": 6.5, "UTILITY": 1.8}[role]
    kills = max(0, int(rng.gauss(base_k * kda_mult, 2.2)))
    deaths = max(0, int(rng.gauss(5.2 / max(kda_mult, 0.4), 1.8)))
    assists = max(0, int(rng.gauss((9.5 if role == "UTILITY" else 6.0) * kda_mult, 3.0)))

    cs_pm = {"TOP": 7.4, "JUNGLE": 5.8, "MIDDLE": 8.0, "BOTTOM": 8.6, "UTILITY": 1.2}[role]
    cs = max(10, int(rng.gauss(cs_pm * minutes, 18)))
    gold = int((cs * 21 + kills * 300 + assists * 150) * rng.uniform(0.9, 1.1)) + 2500
    damage = int(gold * rng.uniform(1.1, 1.9 if cls in ("Mage", "Marksman") else 1.4))

    pool = ITEM_POOLS[cls]
    n_items = 5 if minutes > 30 else (4 if minutes > 24 else 3)
    core = rng.sample(pool, k=min(n_items, len(pool)))
    items = [BOOTS[cls], *core] + [0] * 5
    items = items[:6]

    spells = rng.choice(SPELLS_BY_ROLE[role])
    style, keystones, subs = RUNES[cls]
    keystone = rng.choices(keystones, weights=[3, 2, 1][: len(keystones)] + [1] * max(0, len(keystones) - 3))[0]
    sub_style = rng.choices(subs, weights=[3, 2, 1][: len(subs)] + [1] * max(0, len(subs) - 3))[0]
    fillers = FILLER_PERKS[style]
    sub_fillers = FILLER_PERKS[sub_style]

    return {
        "assists": assists,
        "champLevel": min(18, 11 + int(minutes / 3.2) + (1 if win else 0)),
        "championId": cid,
        "championName": info["key"],
        "deaths": deaths,
        "goldEarned": gold,
        "item0": items[0], "item1": items[1], "item2": items[2],
        "item3": items[3], "item4": items[4], "item5": items[5],
        "item6": rng.choice(TRINKETS),
        "kills": kills,
        "neutralMinionsKilled": cs if role == "JUNGLE" else int(cs * 0.05),
        "participantId": pid,
        "perks": {
            "statPerks": {"defense": 5002, "flex": 5008, "offense": 5008},
            "styles": [
                {"description": "primaryStyle", "style": style,
                 "selections": [{"perk": keystone, "var1": 0, "var2": 0, "var3": 0}]
                 + [{"perk": p, "var1": 0, "var2": 0, "var3": 0} for p in fillers]},
                {"description": "subStyle", "style": sub_style,
                 "selections": [{"perk": p, "var1": 0, "var2": 0, "var3": 0} for p in sub_fillers[:2]]},
            ],
        },
        "puuid": f"DEMO-{_h(f'puuid:{pid}:{cid}'):.8f}-{pid:03d}",
        "riotIdGameName": f"DemoPlayer{rng.randint(1, 9999)}",
        "riotIdTagline": "NA1",
        "summoner1Id": spells[0],
        "summoner2Id": spells[1],
        "summonerName": f"DemoPlayer{rng.randint(1, 9999)}",
        "teamId": team_id,
        "teamPosition": role,
        "totalDamageDealtToChampions": damage,
        "totalMinionsKilled": cs if role != "JUNGLE" else int(cs * 0.35),
        "visionScore": int(rng.gauss(55 if role == "UTILITY" else 22, 8)),
        "win": win,
    }


def _match(rng: random.Random, world: DemoWorld, seq: int, patch: str) -> tuple[str, str]:
    duration = rng.randint(1450, 2350)
    picks: dict[tuple[int, str], int] = {}
    taken: set[int] = set()
    for team_id in (100, 200):
        for role in ROLES:
            cid = world.pick(rng, role, taken)
            taken.add(cid)
            picks[(team_id, role)] = cid

    # Winner from champion strengths + per-lane matchup noise
    diff = 0.0
    for role in ROLES:
        a, b = picks[(100, role)], picks[(200, role)]
        edge = world.wr[(a, patch)] - world.wr[(b, patch)]
        edge += (_h(f"mu:{min(a, b)}:{max(a, b)}") - 0.5) * (0.06 if a < b else -0.06)
        diff += edge
    # k=4 keeps per-champion winrates in a realistic 44-56% band
    p100 = 1 / (1 + math.exp(-4 * diff))
    win100 = rng.random() < p100

    participants = []
    pid = 1
    for team_id in (100, 200):
        for role in ROLES:
            win = win100 if team_id == 100 else not win100
            participants.append(_participant(rng, world, picks[(team_id, role)], role,
                                             team_id, win, pid, duration))
            pid += 1

    ban_ids, ban_w = world.ban_weights(patch)
    bans = rng.choices(ban_ids, weights=ban_w, k=10)
    teams = []
    for idx, team_id in enumerate((100, 200)):
        teams.append({
            "teamId": team_id,
            "win": win100 if team_id == 100 else not win100,
            "bans": [{"championId": (b if rng.random() > 0.03 else -1), "pickTurn": i + 1}
                     for i, b in enumerate(bans[idx * 5:idx * 5 + 5])],
            "objectives": {"champion": {"first": False, "kills": sum(p["kills"] for p in participants
                                                                    if p["teamId"] == team_id)}},
        })

    days_ago = rng.uniform(1, 12) + (0 if patch == PATCHES[-1] else 13)
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    start_ms = int(start.timestamp() * 1000)
    match_id = f"NA1_DEMO{seq:08d}"
    game_version = f"{patch}.{rng.randint(600, 720)}.{rng.randint(1000, 9999)}"

    payload = {
        "metadata": {"dataVersion": "2", "matchId": match_id,
                     "participants": [p["puuid"] for p in participants]},
        "info": {
            "endOfGameResult": "GameComplete",
            "gameCreation": start_ms - 60000,
            "gameDuration": duration,
            "gameEndTimestamp": start_ms + duration * 1000,
            "gameId": 4000000000 + seq,
            "gameMode": "CLASSIC",
            "gameName": f"teambuilder-match-{4000000000 + seq}",
            "gameStartTimestamp": start_ms,
            "gameType": "MATCHED_GAME",
            "gameVersion": game_version,
            "mapId": 11,
            "participants": participants,
            "platformId": "NA1",
            "queueId": 420,
            "teams": teams,
            "tournamentCode": "",
        },
    }
    return match_id, json.dumps(payload, separators=(",", ":"))


def seed(matches: int = 6000, seed_value: int = 20260903) -> int:
    rng = random.Random(seed_value)
    conn = db.open_db()
    ddragon.sync_champions(conn)
    world = DemoWorld(ddragon.load_champions(conn))
    print(f"seeding {matches} demo matches across patches {PATCHES}...")

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    stored = 0
    for seq in range(1, matches + 1):
        patch = PATCHES[-1] if rng.random() < LATEST_SHARE else rng.choice(PATCHES[:-1])
        match_id, raw = _match(rng, world, seq, patch)
        conn.execute(
            "INSERT OR REPLACE INTO raw_matches (match_id, json, source, fetched_at) VALUES (?, ?, 'demo', ?)",
            (match_id, raw, now),
        )
        stored += 1
        if seq % 500 == 0:
            conn.commit()
            print(f"  {seq}/{matches}")
    conn.commit()
    conn.close()
    print(f"done: {stored} demo matches stored")
    return stored


def purge_demo() -> int:
    conn = db.open_db()
    cur = conn.execute("DELETE FROM raw_matches WHERE source = 'demo'")
    conn.commit()
    print(f"purged {cur.rowcount} demo matches (re-run aggregate to refresh stats)")
    conn.close()
    return cur.rowcount
