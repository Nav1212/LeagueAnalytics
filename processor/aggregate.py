"""Build the aggregate (serving) tables from the raw match layer.

Reads every stored Match-V5 payload and rolls up, per patch + champion + role:
win/pick/ban counts, KDA/gold/damage/CS totals, lane matchups, core item
builds, summoner spell sets and rune (keystone + secondary tree) sets.

This step is idempotent: it wipes and rebuilds the aggregate tables from raw
data, so it can be re-run any time (e.g. after fetching more matches).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from . import db, ddragon

ROLES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
RANKED_SOLO = 420

# Item ids that are never part of a "core build" (trinkets, consumables, wards)
NON_CORE_ITEMS = {0, 3340, 3363, 3364, 2003, 2031, 2033, 2055, 2138, 2139, 2140, 3400}


def patch_of(game_version: str) -> str:
    parts = game_version.split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else game_version


def core_items(p: dict) -> list[int]:
    items = [p.get(f"item{i}", 0) for i in range(6)]
    return [i for i in items if i and i not in NON_CORE_ITEMS][:3]


def keystone_and_substyle(p: dict) -> tuple[int, int]:
    try:
        styles = p["perks"]["styles"]
        primary = next(s for s in styles if s.get("description") == "primaryStyle")
        sub = next(s for s in styles if s.get("description") == "subStyle")
        return primary["selections"][0]["perk"], sub["style"]
    except (KeyError, IndexError, StopIteration, TypeError):
        return 0, 0


def aggregate() -> None:
    conn = db.open_db()
    ddragon.load_champions(conn)  # ensure champion identity cache exists

    stats = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])  # (patch,cid,role) -> [g,w,k,d,a,gold,dmg,cs]
    bans = defaultdict(int)                                # (patch,cid) -> bans
    matchups = defaultdict(lambda: [0, 0])                 # (patch,cid,role,opp) -> [g,w]
    builds = defaultdict(lambda: [0, 0])                   # (patch,cid,role,items_json) -> [g,w]
    spells = defaultdict(lambda: [0, 0])                   # (patch,cid,role,spells_json) -> [g,w]
    runes = defaultdict(lambda: [0, 0])                    # (patch,cid,role,ks,sub) -> [g,w]
    patch_matches = defaultdict(int)

    total = skipped = 0
    for row in conn.execute("SELECT json FROM raw_matches"):
        try:
            info = json.loads(row["json"])["info"]
        except (json.JSONDecodeError, KeyError):
            skipped += 1
            continue
        if info.get("queueId") != RANKED_SOLO or info.get("gameDuration", 0) < 300:
            skipped += 1  # non-ranked or remake
            continue

        patch = patch_of(info.get("gameVersion", "0.0"))
        patch_matches[patch] += 1
        total += 1

        by_role_team: dict[tuple[str, int], int] = {}
        for p in info.get("participants", []):
            cid, role = p.get("championId"), p.get("teamPosition", "")
            if not cid or role not in ROLES:
                continue
            win = 1 if p.get("win") else 0
            s = stats[(patch, cid, role)]
            s[0] += 1
            s[1] += win
            s[2] += p.get("kills", 0)
            s[3] += p.get("deaths", 0)
            s[4] += p.get("assists", 0)
            s[5] += p.get("goldEarned", 0)
            s[6] += p.get("totalDamageDealtToChampions", 0)
            s[7] += p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
            by_role_team[(role, p.get("teamId", 0))] = cid

            ci = core_items(p)
            if ci:
                builds[(patch, cid, role, json.dumps(sorted(ci)))][0] += 1
                builds[(patch, cid, role, json.dumps(sorted(ci)))][1] += win
            sp = json.dumps(sorted([p.get("summoner1Id", 0), p.get("summoner2Id", 0)]))
            spells[(patch, cid, role, sp)][0] += 1
            spells[(patch, cid, role, sp)][1] += win
            ks, sub = keystone_and_substyle(p)
            if ks:
                runes[(patch, cid, role, ks, sub)][0] += 1
                runes[(patch, cid, role, ks, sub)][1] += win

        # lane matchups: same role, opposite team
        for p in info.get("participants", []):
            cid, role = p.get("championId"), p.get("teamPosition", "")
            if not cid or role not in ROLES:
                continue
            opp = by_role_team.get((role, 200 if p.get("teamId") == 100 else 100))
            if opp and opp != cid:
                m = matchups[(patch, cid, role, opp)]
                m[0] += 1
                m[1] += 1 if p.get("win") else 0

        for team in info.get("teams", []):
            for ban in team.get("bans", []):
                if ban.get("championId", -1) > 0:
                    bans[(patch, ban["championId"])] += 1

    print(f"aggregated {total} ranked matches ({skipped} skipped)")

    with conn:  # single transaction: wipe + rebuild
        for table in ("champion_stats", "champion_bans", "matchups", "builds",
                      "spell_sets", "rune_sets", "patch_totals"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            "INSERT INTO patch_totals (patch, matches) VALUES (?, ?)",
            list(patch_matches.items()))
        conn.executemany(
            "INSERT INTO champion_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(p, c, r, *v) for (p, c, r), v in stats.items()])
        conn.executemany(
            "INSERT INTO champion_bans VALUES (?, ?, ?)",
            [(p, c, n) for (p, c), n in bans.items()])
        conn.executemany(
            "INSERT INTO matchups VALUES (?, ?, ?, ?, ?, ?)",
            [(p, c, r, o, *v) for (p, c, r, o), v in matchups.items()])
        conn.executemany(
            "INSERT INTO builds VALUES (?, ?, ?, ?, ?, ?)",
            [(p, c, r, i, *v) for (p, c, r, i), v in builds.items()])
        conn.executemany(
            "INSERT INTO spell_sets VALUES (?, ?, ?, ?, ?, ?)",
            [(p, c, r, s, *v) for (p, c, r, s), v in spells.items()])
        conn.executemany(
            "INSERT INTO rune_sets VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(p, c, r, k, s2, *v) for (p, c, r, k, s2), v in runes.items()])
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('aggregated_at', ?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),))
    conn.close()
    print(f"aggregate tables rebuilt: {len(stats)} champion/role rows, "
          f"{len(matchups)} matchup rows, {len(builds)} build rows")
