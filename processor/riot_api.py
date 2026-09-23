"""Minimal Riot Games API client with dev-key-friendly rate limiting.

All successful responses can be passed to a bronze recorder before any caller
parses them. This keeps ingestion lossless while endpoint-specific silver jobs
remain independent.

Responses are returned as *raw text* alongside the parsed JSON so the caller
can store exactly what the API sent.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

# Dev keys allow 20 req / 1 s and 100 req / 120 s. We pace conservatively.
MIN_INTERVAL_S = 1.25  # ~96 requests / 120 s


class RiotAPIError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status


class RiotClient:
    def __init__(
        self,
        api_key: str | None = None,
        platform: str = "na1",
        region: str = "americas",
        recorder: Callable[[str, str, str, str, str, dict[str, Any]], None] | None = None,
    ):
        self.api_key = api_key or os.environ.get("RIOT_API_KEY", "")
        if not self.api_key:
            raise RiotAPIError(401, "(init)", "RIOT_API_KEY is not set")
        self.platform = platform  # e.g. na1, euw1, kr
        self.region = region      # e.g. americas, europe, asia
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = self.api_key
        self.recorder = recorder

    # ------------------------------------------------------------------ core
    def _get(
        self,
        url: str,
        params: dict | None = None,
        *,
        dataset: str,
        routing_value: str,
        natural_key: str,
        allow_not_found: bool = False,
    ) -> tuple[str, object] | None:
        """GET with pacing + 429/5xx retry. Returns (raw_text, parsed_json)."""
        for attempt in range(6):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                if self.recorder:
                    self.recorder(
                        dataset, routing_value, natural_key, url, resp.text, params or {}
                    )
                return resp.text, resp.json()
            if resp.status_code == 404 and allow_not_found:
                return None
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "10"))
                print(f"    rate limited; sleeping {retry_after}s")
                time.sleep(retry_after + 1)
                continue
            if resp.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise RiotAPIError(resp.status_code, url, resp.text)
        raise RiotAPIError(429, url, "retries exhausted")

    # --------------------------------------------------------------- ladders
    def top_ladder_entries(self, queue: str = "RANKED_SOLO_5x5") -> list[dict]:
        """Challenger + grandmaster + master league entries (includes puuid)."""
        entries: list[dict] = []
        for tier in ("challengerleagues", "grandmasterleagues", "masterleagues"):
            url = f"https://{self.platform}.api.riotgames.com/lol/league/v4/{tier}/by-queue/{queue}"
            result = self._get(
                url,
                dataset="league-v4.apex-league",
                routing_value=self.platform,
                natural_key=f"{queue}:{tier}",
            )
            assert result is not None
            _, data = result
            entries.extend(data.get("entries", []))
        return entries

    def league_entries(
        self, queue: str, tier: str, division: str, page: int = 1
    ) -> list[dict]:
        url = (
            f"https://{self.platform}.api.riotgames.com/lol/league/v4/entries/"
            f"{queue}/{tier}/{division}"
        )
        result = self._get(
            url,
            params={"page": page},
            dataset="league-v4.entries",
            routing_value=self.platform,
            natural_key=f"{queue}:{tier}:{division}:{page}",
        )
        assert result is not None
        return list(result[1])

    def league_exp_entries(
        self, queue: str, tier: str, division: str, page: int = 1
    ) -> list[dict]:
        url = (
            f"https://{self.platform}.api.riotgames.com/lol/league-exp/v4/entries/"
            f"{queue}/{tier}/{division}"
        )
        result = self._get(
            url,
            params={"page": page},
            dataset="league-exp-v4.entries",
            routing_value=self.platform,
            natural_key=f"{queue}:{tier}:{division}:{page}",
        )
        assert result is not None
        return list(result[1])

    # --------------------------------------------------------------- matches
    def match_ids_by_puuid(
        self, puuid: str, count: int = 20, queue: int | None = None, start: int = 0
    ) -> list[str]:
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"start": start, "count": count}
        if queue is not None:
            params["queue"] = queue
        result = self._get(
            url,
            params=params,
            dataset="match-v5.match-ids",
            routing_value=self.region,
            natural_key=f"{puuid}:{queue if queue is not None else 'all'}:{start}:{count}",
        )
        assert result is not None
        _, data = result
        return list(data)

    def match(self, match_id: str) -> tuple[str, dict]:
        """Full match payload. Returns (raw_text_exactly_as_received, parsed)."""
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        result = self._get(
            url,
            dataset="match-v5.match",
            routing_value=self.region,
            natural_key=match_id,
        )
        assert result is not None
        return result  # type: ignore[return-value]

    def timeline(self, match_id: str) -> tuple[str, dict]:
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
        result = self._get(
            url,
            dataset="match-v5.timeline",
            routing_value=self.region,
            natural_key=match_id,
        )
        assert result is not None
        return result  # type: ignore[return-value]

    # ---------------------------------------------------------- global data
    def champion_rotation(self) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/platform/v3/champion-rotations"
        result = self._get(
            url, dataset="champion-v3.rotation", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return dict(result[1])

    def platform_status(self) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/status/v4/platform-data"
        result = self._get(
            url, dataset="lol-status-v4.platform-data", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return dict(result[1])

    def challenge_configs(self) -> list[dict]:
        url = f"https://{self.platform}.api.riotgames.com/lol/challenges/v1/challenges/config"
        result = self._get(
            url, dataset="lol-challenges-v1.config", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return list(result[1])

    def challenge_percentiles(self) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/challenges/v1/challenges/percentiles"
        result = self._get(
            url, dataset="lol-challenges-v1.percentiles", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return dict(result[1])

    def featured_games(self) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/spectator/v5/featured-games"
        result = self._get(
            url, dataset="spectator-v5.featured-games", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return dict(result[1])

    def clash_tournaments(self) -> list[dict]:
        url = f"https://{self.platform}.api.riotgames.com/lol/clash/v1/tournaments"
        result = self._get(
            url, dataset="clash-v1.tournaments", routing_value=self.platform,
            natural_key=self.platform,
        )
        assert result is not None
        return list(result[1])

    # ---------------------------------------------------------- player data
    def account_by_puuid(self, puuid: str) -> dict:
        url = f"https://{self.region}.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
        result = self._get(
            url, dataset="account-v1.account", routing_value=self.region,
            natural_key=puuid,
        )
        assert result is not None
        return dict(result[1])

    def summoner_by_puuid(self, puuid: str) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        result = self._get(
            url, dataset="summoner-v4.summoner", routing_value=self.platform,
            natural_key=puuid,
        )
        assert result is not None
        return dict(result[1])

    def champion_masteries(self, puuid: str) -> list[dict]:
        url = (
            f"https://{self.platform}.api.riotgames.com/lol/champion-mastery/v4/"
            f"champion-masteries/by-puuid/{puuid}"
        )
        result = self._get(
            url, dataset="champion-mastery-v4.masteries", routing_value=self.platform,
            natural_key=puuid,
        )
        assert result is not None
        return list(result[1])

    def champion_mastery_score(self, puuid: str) -> int:
        url = (
            f"https://{self.platform}.api.riotgames.com/lol/champion-mastery/v4/"
            f"scores/by-puuid/{puuid}"
        )
        result = self._get(
            url, dataset="champion-mastery-v4.score", routing_value=self.platform,
            natural_key=puuid,
        )
        assert result is not None
        return int(result[1])

    def player_challenges(self, puuid: str) -> dict:
        url = f"https://{self.platform}.api.riotgames.com/lol/challenges/v1/player-data/{puuid}"
        result = self._get(
            url, dataset="lol-challenges-v1.player-data", routing_value=self.platform,
            natural_key=puuid,
        )
        assert result is not None
        return dict(result[1])

    def active_game(self, puuid: str) -> dict | None:
        url = f"https://{self.platform}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
        result = self._get(
            url, dataset="spectator-v5.active-game", routing_value=self.platform,
            natural_key=puuid, allow_not_found=True,
        )
        return None if result is None else dict(result[1])
