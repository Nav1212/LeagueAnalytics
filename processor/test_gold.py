from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from . import db, ddragon, gold, rebuild, seed_demo, staging
from .test_fixtures import publish_fixture


class PublicationTests(unittest.TestCase):
    def test_rebuild_publishes_static_icons_and_separate_match_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {"CHAMPIONGG_DB":str(root / "private.db"), "CHAMPIONGG_GOLD_DIR":str(root / "gold")}):
                with patch("processor.ddragon.requests.get", side_effect=OSError("offline fixture")):
                    seed_demo.seed(matches=2)
                c = db.open_db()
                raw = json.loads(c.execute("SELECT json FROM bronze_matches LIMIT 1").fetchone()[0])
                raw["metadata"]["matchId"] = "NA1_REAL"
                timeline = {"metadata":{"matchId":"NA1_REAL"}, "info":{"frameInterval":60000,
                    "frames":[{"timestamp":0,"participantFrames":{"1":{"participantId":1,"totalGold":500}},"events":[]}]}}
                with c:
                    c.execute("INSERT INTO bronze_matches VALUES ('NA1_REAL',?,'riot',?)", (json.dumps(raw), db.utcnow()))
                    c.execute("INSERT INTO bronze_match_timelines VALUES ('NA1_REAL',?,'riot',?)", (json.dumps(timeline), db.utcnow()))
                    old_styles = [{"id":8400,"key":"OldStyle","name":"Removed Style","icon":"old.png","slots":[]}]
                    db.store_bronze_payload(c, source="ddragon", dataset="ddragon.runes", natural_key="16.17.1:en_US",
                        routing_value="16.17.1", request_url="https://example.test/runes", response_json=json.dumps(old_styles), fetched_at="2000-01-01T00:00:00+00:00")
                    for locale, name in [("en_US","English Rune"),("fr_FR","French Rune")]:
                        styles = [{"id":8000,"key":"Precision","name":"Precision","icon":"style.png",
                            "slots":[{"runes":[{"id":8005,"key":"Test","name":name,"icon":"rune.png"}]}]}]
                        db.store_bronze_payload(c, source="ddragon", dataset="ddragon.runes", natural_key=f"16.17.1:{locale}",
                            routing_value="16.17.1", request_url="https://example.test/runes", response_json=json.dumps(styles), fetched_at=db.utcnow())
                    c.execute("INSERT INTO meta VALUES ('ddragon_version','16.17.1')")
                c.close()
                report = rebuild.rebuild(threads=2, memory_limit="512MB")
                self.assertEqual(report["status"], "complete")
                target = sqlite3.connect(root / "gold" / report["publication"]["snapshot"])
                try:
                    counts = dict(target.execute("SELECT source,sum(matches) FROM gold_patch_totals GROUP BY source"))
                    self.assertEqual(counts, {"demo":2,"riot":1})
                    catalog = json.loads(target.execute("SELECT styles FROM gold_rune_catalog WHERE locale='en_US'").fetchone()[0])
                    self.assertEqual([style["id"] for style in catalog], [8000])
                    self.assertEqual(catalog[0]["icon"], "style.png")
                    self.assertEqual(catalog[0]["slots"][0]["runes"][0]["name"], "English Rune")
                    self.assertEqual(catalog[0]["slots"][0]["runes"][0]["icon"], "rune.png")
                finally:
                    target.close()
                # Re-observing an older deduplicated body must make it current.
                c = db.open_db()
                with c:
                    db.store_bronze_payload(c, source="ddragon", dataset="ddragon.runes", natural_key="16.17.1:en_US",
                        routing_value="16.17.1", request_url="https://example.test/runes", response_json=json.dumps(old_styles), fetched_at="2099-01-01T00:00:00+00:00")
                c.close()
                report = rebuild.rebuild(threads=2, memory_limit="512MB")
                self.assertEqual(report["status"], "complete")
                target = sqlite3.connect(root / "gold" / report["publication"]["snapshot"])
                try:
                    catalog = json.loads(target.execute("SELECT styles FROM gold_rune_catalog WHERE locale='en_US'").fetchone()[0])
                    self.assertEqual([style["id"] for style in catalog], [8400])
                finally:
                    target.close()

    def test_snapshot_is_public_readonly_and_failed_publication_preserves_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = publish_fixture(directory, "first")
            current = (directory / "current.json").read_bytes()
            with self.assertRaises(duckdb.Error):
                publish_fixture(directory, "broken", "broken")
            self.assertEqual(current, (directory / "current.json").read_bytes())
            filename = directory / first["snapshot"]
            connection = sqlite3.connect(filename.as_uri() + "?mode=ro", uri=True)
            try:
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                self.assertEqual(tables, {"gold_" + name for name in gold.TABLES})
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertIsNone(connection.execute("SELECT value FROM gold_meta WHERE key='analytics_snapshot'").fetchone())
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM gold_champions")
            finally:
                connection.close()
            self.assertFalse(list(directory.glob("*-wal")))
            self.assertFalse(list(directory.glob("*-shm")))
            publish_fixture(directory, "second")
            publish_fixture(directory, "third")
            self.assertEqual({p.name for p in directory.glob("gold-*.sqlite")}, {"gold-second.sqlite", "gold-third.sqlite"})

    def test_failed_manifest_switch_preserves_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            publish_fixture(directory, "first")
            current = (directory / "current.json").read_bytes()
            replace = os.replace
            def fail_manifest(src, dest):
                if Path(dest).name == "current.json":
                    raise OSError("simulated interrupted publication")
                replace(src, dest)
            with patch("processor.gold.os.replace", side_effect=fail_manifest):
                with self.assertRaises(OSError):
                    publish_fixture(directory, "second")
            self.assertEqual(current, (directory / "current.json").read_bytes())

    def test_cleanup_defers_locked_files_without_failing_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            publish_fixture(directory, "first")
            publish_fixture(directory, "second")
            unlink = Path.unlink
            def defer(path, *args, **kwargs):
                if path.name == "gold-first.sqlite":
                    raise PermissionError("open Windows reader")
                return unlink(path, *args, **kwargs)
            with patch.object(Path, "unlink", defer):
                publish_fixture(directory, "third")
            self.assertEqual(json.loads((directory / "current.json").read_text())["runId"], "third")
            self.assertTrue((directory / "gold-first.sqlite").exists())
            publish_fixture(directory, "fourth")
            self.assertEqual({p.name for p in directory.glob("gold-*.sqlite")}, {"gold-third.sqlite", "gold-fourth.sqlite"})

    def test_canonical_rebuild_handles_offline_demo_and_rejects_bad_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {"CHAMPIONGG_DB":str(root / "private.db"), "CHAMPIONGG_GOLD_DIR":str(root / "gold")}):
                with patch("processor.ddragon.requests.get", side_effect=OSError("offline fixture")):
                    seed_demo.seed(matches=8)
                c = db.open_db()
                with c:
                    c.execute("INSERT INTO rebuild_runs(run_id,started_at,status) VALUES ('interrupted',?,'running')", (db.utcnow(),))
                c.close()
                report = rebuild.rebuild(threads=2, memory_limit="512MB")
                self.assertEqual(report["status"], "complete")
                current = (root / "gold" / "current.json").read_bytes()
                c = db.open_db()
                self.assertEqual(c.execute("SELECT status FROM rebuild_runs WHERE run_id='interrupted'").fetchone()[0], "failed")
                with c:
                    c.execute("INSERT INTO bronze_matches VALUES ('BAD','{}','riot',?)", (db.utcnow(),))
                c.close()
                report = rebuild.rebuild(threads=2, memory_limit="512MB")
                self.assertEqual(report["status"], "partial")
                self.assertEqual(current, (root / "gold" / "current.json").read_bytes())


class StaticIngestionTests(unittest.TestCase):
    def test_optional_fields_nullable_but_wrong_nested_types_rejected(self):
        with duckdb.connect() as c:
            schema = {"items":[{"id":"BIGINT", "name":"VARCHAR"}]}
            for payload, valid in [('{"items":[{"id":1}]}', True), ('{"items":[{"id":"wrong"}]}', False), ('{"items":"wrong"}', False)]:
                c.execute("CREATE OR REPLACE TEMP TABLE fixture AS SELECT ? AS raw", [payload])
                value = c.execute(f"SELECT {staging.parse_sql('raw',schema)} FROM fixture").fetchone()[0]
                self.assertEqual(value is not None, valid)

    def test_seed_and_full_static_use_exact_recording_and_retain_failed_runes(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        db.init_schema(c)
        rune_body = '[ {"id":8000,"name":"Precision","icon":"style.png","slots":[]} ]'
        class Response:
            def __init__(self, text): self.text = text
            def raise_for_status(self): pass
            def json(self): return json.loads(self.text)
        def get(url, **kwargs):
            if url.endswith("versions.json"): return Response('["16.10.1"]')
            if url.endswith("champion.json"): return Response('{"data":{"Ahri":{"key":"1","name":"Ahri","tags":["Mage"]}}}')
            if url.endswith("runesReforged.json"): return Response(rune_body)
            return Response('[]' if url.endswith("languages.json") else '{"data":{}}')
        try:
            with patch("processor.ddragon.requests.get", side_effect=get):
                ddragon.sync_champions(c)
                ddragon.sync_all_static(c, champion_details=False)
            rows = c.execute("SELECT response_json FROM bronze_payloads WHERE dataset='ddragon.runes'").fetchall()
            self.assertEqual([r[0] for r in rows], [rune_body])
            with patch("processor.ddragon.requests.get", side_effect=OSError("offline")):
                ddragon.sync_champions(c)
            self.assertEqual(c.execute("SELECT name FROM champions WHERE champion_id=1").fetchone()[0], "Ahri")
            self.assertEqual(c.execute("SELECT response_json FROM bronze_payloads WHERE dataset='ddragon.runes'").fetchone()[0], rune_body)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
