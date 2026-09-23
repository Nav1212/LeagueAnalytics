"""Champion.GG-Revitalization data processor CLI.

Usage:
  python -m processor.main seed [--matches N]         seed demo data (no API key)
  python -m processor.main fetch [--max N] [--platform na1 --region americas]
                                                      fetch League bronze (RIOT_API_KEY)
  python -m processor.main sync-static                fetch static bronze (no API key)
  python -m processor.main setup                      install the DuckDB SQLite extension
  python -m processor.main aggregate                  validate Silver and publish Gold
  python -m processor.main purge-demo                 drop demo rows from bronze
  python -m processor.main status                     show database contents
"""

from __future__ import annotations

import argparse

from . import aggregate as agg
from . import db, ddragon, seed_demo, gold


def status() -> None:
    conn = db.open_db()
    raw = conn.execute(
        "SELECT source, COUNT(*) AS n FROM bronze_matches GROUP BY source").fetchall()
    print(f"database: {db.db_path()}")
    print("bronze_matches:", {r["source"]: r["n"] for r in raw} or "empty")
    timelines = conn.execute("SELECT COUNT(*) AS n FROM bronze_match_timelines").fetchone()["n"]
    payloads = conn.execute("SELECT COUNT(*) AS n FROM bronze_payloads").fetchone()["n"]
    print(f"bronze_match_timelines: {timelines} rows")
    print(f"bronze_payloads: {payloads} versions")
    for row in conn.execute(
        "SELECT dataset, COUNT(*) AS n FROM bronze_payloads GROUP BY dataset ORDER BY dataset"
    ):
        print(f"  {row['dataset']}: {row['n']}")
    for table in ("champions",):
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        print(f"{table}: {n} rows")
    for row in conn.execute("SELECT * FROM meta"):
        print(f"meta {row['key']} = {row['value']}")
    conn.close()
    manifest = gold.gold_dir() / "current.json"
    print(f"Gold publication: {manifest}")
    print(manifest.read_text(encoding="utf-8") if manifest.exists() else "not published")


def sync_static(
    champion_details: bool = True, locale: str = "en_US", realm: str = "na"
) -> None:
    conn = db.open_db()
    run_id = db.start_fetch_run(
        conn, "league-static",
        {"champion_details": champion_details, "locale": locale, "realm": realm},
    )
    try:
        result = ddragon.sync_all_static(
            conn, fetch_run_id=run_id, champion_details=champion_details,
            locale=locale, realm=realm,
        )
        status_value = "complete" if int(result["errors"]) == 0 else "partial"
        db.finish_fetch_run(conn, run_id, status=status_value)
        print(
            f"static bronze: version {result['version']}, "
            f"{result['stored']} payloads stored, {result['errors']} errors"
        )
    except Exception as exc:
        db.finish_fetch_run(conn, run_id, status="failed", error=str(exc))
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="processor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="seed demo matches (no API key needed)")
    p_seed.add_argument("--matches", type=int, default=6000)

    p_fetch = sub.add_parser("fetch", help="fetch the League bronze dataset from Riot")
    p_fetch.add_argument("--max", type=int, default=500)
    p_fetch.add_argument("--players", type=int, default=50)
    p_fetch.add_argument("--per-player", type=int, default=20)
    p_fetch.add_argument("--platform", default="na1")
    p_fetch.add_argument("--region", default="americas")
    p_fetch.add_argument("--league-pages", type=int, default=1)
    p_fetch.add_argument("--no-timelines", action="store_true")
    p_fetch.add_argument("--no-player-data", action="store_true")
    p_fetch.add_argument("--no-static", action="store_true")

    p_static = sub.add_parser("sync-static", help="fetch Data Dragon and Riot reference bronze")
    p_static.add_argument("--no-champion-details", action="store_true")
    p_static.add_argument("--locale", default="en_US")
    p_static.add_argument("--realm", default="na")

    sub.add_parser("setup", help="install the DuckDB SQLite extension (one-time network access)")
    sub.add_parser("aggregate", help="validate Silver and publish a Gold-only snapshot")
    sub.add_parser("purge-demo", help="delete demo rows from bronze_matches")
    sub.add_parser("status", help="show database contents")

    args = parser.parse_args()
    with db.writer_lock():
        if args.cmd == "setup":
            from .rebuild import setup
            setup()
        elif args.cmd == "seed":
            seed_demo.seed(matches=args.matches)
            agg.aggregate()
        elif args.cmd == "fetch":
            from .fetch import fetch_matches  # import here: requires requests/network
            fetch_matches(max_matches=args.max, players=args.players,
                          per_player=args.per_player, platform=args.platform,
                          region=args.region, league_pages=args.league_pages,
                          include_timelines=not args.no_timelines,
                          include_player_data=not args.no_player_data,
                          include_static=not args.no_static)
            agg.aggregate()
        elif args.cmd == "aggregate":
            agg.aggregate()
        elif args.cmd == "sync-static":
            sync_static(
                champion_details=not args.no_champion_details,
                locale=args.locale,
                realm=args.realm,
            )
            agg.aggregate()
        elif args.cmd == "purge-demo":
            seed_demo.purge_demo()
            agg.aggregate()
        elif args.cmd == "status":
            status()


if __name__ == "__main__":
    main()
