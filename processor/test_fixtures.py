"""Deterministic public fixtures; no source API calls or working database access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import duckdb

from . import gold


def create_analytics(filename: Path, mode: str = "normal", revision: int = 1) -> None:
    with duckdb.connect(str(filename)) as c:
        c.execute(gold.SCHEMA)
        if mode == "empty":
            return
        c.executemany("INSERT INTO gold_champions VALUES (?,?,?,?,?)", [
            (1, "Ahri", "Ahri", "the Nine-Tailed Fox", '["Mage"]'),
            (2, "MonkeyKing", "Wukong", "the Monkey King", '["Fighter"]'),
            (3, "Garen", "Garen", "the Might of Demacia", '["Fighter"]'),
            (4, "Lux", "Lux", "the Lady of Luminosity", '["Mage"]'),
            (5, "Annie", "Annie", "the Dark Child", '["Mage"]'),
        ] + [(10+i, f"Test{i:02}", f"Test {i:02}", "", "[]") for i in range(12)])
        c.executemany("INSERT INTO gold_patch_totals VALUES (?,?,?)", [
            ("riot", "16.10", 2000), ("riot", "16.9", 100),
            ("demo", "16.10", 100), ("demo", "16.8", 50)])
        c.executemany("INSERT INTO gold_champion_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            ("riot", "16.10", 1, "MIDDLE", 100, 60 if revision == 1 else 70, 1000, 200, 800, 1234500, 2345678, 22050),
            ("riot", "16.10", 2, "TOP", 16, 8, 32, 16, 48, 16000, 32000, 1600),
            ("riot", "16.10", 3, "TOP", 15, 15, 30, 0, 45, 15000, 30000, 1500),
            ("riot", "16.9", 4, "MIDDLE", 9, 9, 9, 9, 9, 9000, 9000, 900),
            ("riot", "16.9", 5, "MIDDLE", 10, 5, 10, 10, 10, 10000, 10000, 1000),
            ("demo", "16.10", 1, "MIDDLE", 50, 5, 100, 50, 50, 500000, 500000, 5000)])
        c.executemany("INSERT INTO gold_champion_bans VALUES (?,?,?,?)", [
            ("riot", "16.10", 1, 200), ("demo", "16.10", 1, 90)])
        c.executemany("INSERT INTO gold_matchups VALUES (?,?,?,?,?,?,?)", [
            ("riot", "16.10", 1, "MIDDLE", 2, 10, 8),
            ("riot", "16.10", 1, "MIDDLE", 3, 2, 2),
            ("demo", "16.10", 1, "MIDDLE", 2, 50, 5)])
        c.executemany("INSERT INTO gold_builds VALUES (?,?,?,?,?,?,?)", [
            ("riot", "16.10", 1, "MIDDLE", json.dumps([1000+i]), 45-i, 20)
            for i in range(40)
        ] + [("riot", "16.10", 1, "MIDDLE", "[9999]", 3, 3),
             ("riot", "16.10", 1, "MIDDLE", "[9998]", 2, 2),
             ("demo", "16.10", 1, "MIDDLE", "[2000]", 50, 5)])
        # Keep fixture wins within games while distinguishing popularity from win rate.
        c.execute("UPDATE gold_builds SET wins=least(wins,games-1) WHERE source='riot' AND items NOT IN ('[9999]','[9998]')")
        for i in range(4):
            c.execute("INSERT INTO gold_spell_sets VALUES (?,?,?,?,?,?,?)", ["riot", "16.10", 1, "MIDDLE", json.dumps([4, 10+i]), 20-i, 10])
            c.execute("INSERT INTO gold_rune_sets VALUES (?,?,?,?,?,?,?,?)", ["riot", "16.10", 1, "MIDDLE", 8000+i, 8400, 20-i, 10])
        c.execute("INSERT INTO gold_spell_sets VALUES ('demo','16.10',1,'MIDDLE','[4,14]',50,5)")
        c.execute("INSERT INTO gold_rune_sets VALUES ('demo','16.10',1,'MIDDLE',9001,8200,50,5)")
        c.execute("INSERT INTO gold_source_counts VALUES ('riot',2500),('demo',500)")
        c.execute("INSERT INTO gold_meta VALUES ('ddragon_version','16.10.1'),('analytics_snapshot','PRIVATE_PATH_MUST_NOT_LEAK')")
        for version, locale, name in [("16.10.1", "en_US", "Published Rune"), ("16.9.1", "en_US", "Older Rune"), ("16.10.1", "fr_FR", "French Rune")]:
            styles = [{"id":8000,"name":"Precision","icon":"perk-images/Styles/7201_Precision.png",
                       "slots":[{"runes":[{"id":9001,"name":name,"icon":"perk-images/Styles/Test.png"}]}]}]
            c.execute("INSERT INTO gold_rune_catalog VALUES (?,?,?)", [version, locale, json.dumps(styles)])
        if mode == "demo":
            for name in gold.TABLES:
                if gold.TABLES[name][0].startswith("source"):
                    c.execute(f"DELETE FROM gold_{name} WHERE source='riot'")
        if mode == "bad-json":
            c.execute("UPDATE gold_champions SET tags='invalid json' WHERE champion_id=1")
        if mode == "broken":
            c.execute("DROP TABLE gold_champion_stats")


def publish_fixture(directory: Path, run_id: str, mode: str = "normal", revision: int = 1):
    with tempfile.TemporaryDirectory() as temporary:
        analytics = Path(temporary) / "fixture.duckdb"
        create_analytics(analytics, mode, revision)
        return gold.publish(analytics, run_id, directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()
    publish_fixture(args.directory, args.run_id, args.mode, args.revision)
