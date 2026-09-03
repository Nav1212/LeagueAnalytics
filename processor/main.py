"""Champion.GG-Revitalization data processor CLI.

Usage:
  python -m processor.main seed [--matches N]         seed demo data (no API key)
  python -m processor.main fetch [--max N] [--platform na1 --region americas]
                                                      fetch real matches (RIOT_API_KEY)
  python -m processor.main aggregate                  rebuild serving tables from raw
  python -m processor.main purge-demo                 drop demo rows from the raw layer
  python -m processor.main status                     show database contents
"""

from __future__ import annotations

import argparse

from . import aggregate as agg
from . import db, seed_demo


def status() -> None:
    conn = db.open_db()
    raw = conn.execute(
        "SELECT source, COUNT(*) AS n FROM raw_matches GROUP BY source").fetchall()
    print(f"database: {db.db_path()}")
    print("raw_matches:", {r["source"]: r["n"] for r in raw} or "empty")
    for table in ("champions", "champion_stats", "matchups", "builds"):
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        print(f"{table}: {n} rows")
    for row in conn.execute("SELECT * FROM patch_totals ORDER BY patch"):
        print(f"  patch {row['patch']}: {row['matches']} matches")
    for row in conn.execute("SELECT * FROM meta"):
        print(f"meta {row['key']} = {row['value']}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="processor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="seed demo matches (no API key needed)")
    p_seed.add_argument("--matches", type=int, default=6000)

    p_fetch = sub.add_parser("fetch", help="fetch real matches from the Riot API")
    p_fetch.add_argument("--max", type=int, default=500)
    p_fetch.add_argument("--players", type=int, default=50)
    p_fetch.add_argument("--per-player", type=int, default=20)
    p_fetch.add_argument("--platform", default="na1")
    p_fetch.add_argument("--region", default="americas")

    sub.add_parser("aggregate", help="rebuild aggregate tables from raw matches")
    sub.add_parser("purge-demo", help="delete demo rows from raw_matches")
    sub.add_parser("status", help="show database contents")

    args = parser.parse_args()
    if args.cmd == "seed":
        seed_demo.seed(matches=args.matches)
        agg.aggregate()
    elif args.cmd == "fetch":
        from .fetch import fetch_matches  # import here: requires requests/network
        fetch_matches(max_matches=args.max, players=args.players,
                      per_player=args.per_player, platform=args.platform,
                      region=args.region)
        agg.aggregate()
    elif args.cmd == "aggregate":
        agg.aggregate()
    elif args.cmd == "purge-demo":
        seed_demo.purge_demo()
        agg.aggregate()
    elif args.cmd == "status":
        status()


if __name__ == "__main__":
    main()
