from __future__ import annotations

import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from . import db, ddragon
from .riot_api import RiotClient
from .riot_api import RiotAPIError


class BronzeSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        db.init_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_payloads_are_versioned_and_exact_duplicates_are_deduplicated(self) -> None:
        values = dict(
            source="riot-api",
            dataset="match-v5.match",
            routing_value="americas",
            natural_key="NA1_1",
            request_url="https://americas.api.riotgames.com/lol/match/v5/matches/NA1_1",
            request_params="{}",
            fetched_at="2026-01-01T00:00:00+00:00",
        )
        self.assertTrue(db.store_bronze_payload(self.conn, response_json='{"v":1}', **values))
        self.assertFalse(db.store_bronze_payload(self.conn, response_json='{"v":1}', **values))
        self.assertTrue(db.store_bronze_payload(self.conn, response_json='{"v":2}', **values))
        count = self.conn.execute("SELECT COUNT(*) FROM bronze_payloads").fetchone()[0]
        self.assertEqual(count, 2)

    def test_legacy_matches_migrate_non_destructively(self) -> None:
        self.conn.execute(
            "INSERT INTO raw_matches VALUES (?, ?, ?, ?)",
            ("NA1_1", '{"metadata":{}}', "riot", "2026-01-01T00:00:00+00:00"),
        )
        db.init_schema(self.conn)
        row = self.conn.execute(
            "SELECT json, source FROM bronze_matches WHERE match_id = 'NA1_1'"
        ).fetchone()
        self.assertEqual(dict(row), {"json": '{"metadata":{}}', "source": "riot"})

    def test_fetch_run_and_error_lineage(self) -> None:
        run_id = db.start_fetch_run(self.conn, "test", {"platform": "na1"})
        db.record_fetch_error(self.conn, run_id, "test.dataset", "boom", "key")
        db.finish_fetch_run(self.conn, run_id, status="partial")
        run = self.conn.execute(
            "SELECT status, completed_at FROM bronze_fetch_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        self.assertEqual(run["status"], "partial")
        self.assertIsNotNone(run["completed_at"])
        self.assertEqual(
            self.conn.execute(
                "SELECT dataset FROM bronze_fetch_errors WHERE fetch_run_id = ?", (run_id,)
            ).fetchone()[0],
            "test.dataset",
        )

    def test_platform_to_ddragon_realm_mapping(self) -> None:
        self.assertEqual(ddragon.realm_for_platform("NA1"), "na")
        self.assertEqual(ddragon.realm_for_platform("EUW1"), "euw")
        self.assertEqual(ddragon.realm_for_platform("EUN1"), "eune")


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, text: str, value: object):
        self.text = text
        self._value = value

    def json(self) -> object:
        return self._value


class RiotClientBronzeTests(unittest.TestCase):
    @patch("processor.riot_api.MIN_INTERVAL_S", 0)
    def test_match_and_timeline_are_recorded_before_return(self) -> None:
        captured: list[tuple[str, str, str, str]] = []

        def recorder(dataset, routing, key, url, raw, params):
            captured.append((dataset, routing, key, raw))

        client = RiotClient(
            api_key="test", platform="na1", region="americas", recorder=recorder
        )
        client.session.get = unittest.mock.Mock(
            side_effect=[
                _Response('{"info":{}}', {"info": {}}),
                _Response('{"info":{"frames":[]}}', {"info": {"frames": []}}),
            ]
        )
        client.match("NA1_1")
        client.timeline("NA1_1")
        self.assertEqual(
            captured,
            [
                ("match-v5.match", "americas", "NA1_1", '{"info":{}}'),
                (
                    "match-v5.timeline",
                    "americas",
                    "NA1_1",
                    '{"info":{"frames":[]}}',
                ),
            ],
        )


class _FakeRiotClient:
    def __init__(self, *, platform, region, recorder):
        self.platform = platform
        self.region = region
        self.recorder = recorder

    def _land(self, dataset: str, key: str, raw: str) -> None:
        self.recorder(dataset, self.region, key, f"https://example/{dataset}/{key}", raw, {})

    def champion_rotation(self): return {}
    def platform_status(self): return {}
    def challenge_configs(self): return []
    def challenge_percentiles(self): return {}
    def featured_games(self): return {}
    def clash_tournaments(self): return []
    def top_ladder_entries(self): return [{"puuid": "player-1"}]
    def league_entries(self, queue, tier, division, page): return []
    def league_exp_entries(self, queue, tier, division, page): return []
    def match_ids_by_puuid(self, puuid, count, queue=None): return ["NA1_1"]

    def match(self, match_id):
        raw = '{"metadata":{"matchId":"NA1_1"},"info":{}}'
        self._land("match-v5.match", match_id, raw)
        return raw, {"metadata": {"matchId": match_id}, "info": {}}

    def timeline(self, match_id):
        raw = '{"metadata":{"matchId":"NA1_1"},"info":{"frames":[]}}'
        self._land("match-v5.timeline", match_id, raw)
        return raw, {"metadata": {"matchId": match_id}, "info": {"frames": []}}


class BronzePullTests(unittest.TestCase):
    @patch("processor.fetch.RiotClient", _FakeRiotClient)
    def test_pull_lands_keyed_matches_timelines_and_generic_payloads(self) -> None:
        from .fetch import fetch_matches

        with tempfile.TemporaryDirectory() as directory:
            database = f"{directory}/bronze.db"
            with patch.dict("os.environ", {"CHAMPIONGG_DB": database}):
                stored = fetch_matches(
                    max_matches=1,
                    players=1,
                    per_player=1,
                    include_static=False,
                    include_player_data=False,
                )
                self.assertEqual(stored, 1)
                conn = sqlite3.connect(database)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM bronze_matches").fetchone()[0], 1)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM bronze_match_timelines").fetchone()[0], 1
                )
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM bronze_payloads").fetchone()[0], 2)
                self.assertEqual(
                    conn.execute("SELECT status FROM bronze_fetch_runs").fetchone()[0], "complete"
                )
                conn.close()

    def test_missing_api_key_marks_run_failed(self) -> None:
        from .fetch import fetch_matches

        with tempfile.TemporaryDirectory() as directory:
            database = f"{directory}/bronze.db"
            with patch.dict(
                "os.environ", {"CHAMPIONGG_DB": database, "RIOT_API_KEY": ""}
            ):
                with self.assertRaises(RiotAPIError):
                    fetch_matches(max_matches=1, include_static=False)
                conn = sqlite3.connect(database)
                status = conn.execute("SELECT status FROM bronze_fetch_runs").fetchone()[0]
                self.assertEqual(status, "failed")
                conn.close()


if __name__ == "__main__":
    unittest.main()
