"""Minimal Riot Games API client with dev-key-friendly rate limiting.

Only the endpoints the pipeline needs:
  - league-v4:  top-ladder players (challenger/grandmaster/master)
  - match-v5:   match ids by puuid, and full match payloads

Responses are returned as *raw text* alongside the parsed JSON so the caller
can store exactly what the API sent.
"""

from __future__ import annotations

import os
import time

import requests

# Dev keys allow 20 req / 1 s and 100 req / 120 s. We pace conservatively.
MIN_INTERVAL_S = 1.25  # ~96 requests / 120 s


class RiotAPIError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status


class RiotClient:
    def __init__(self, api_key: str | None = None, platform: str = "na1", region: str = "americas"):
        self.api_key = api_key or os.environ.get("RIOT_API_KEY", "")
        if not self.api_key:
            raise RiotAPIError(401, "(init)", "RIOT_API_KEY is not set")
        self.platform = platform  # e.g. na1, euw1, kr
        self.region = region      # e.g. americas, europe, asia
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = self.api_key

    # ------------------------------------------------------------------ core
    def _get(self, url: str, params: dict | None = None) -> tuple[str, object]:
        """GET with pacing + 429/5xx retry. Returns (raw_text, parsed_json)."""
        for attempt in range(6):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.text, resp.json()
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
            _, data = self._get(url)
            entries.extend(data.get("entries", []))
        return entries

    # --------------------------------------------------------------- matches
    def match_ids_by_puuid(self, puuid: str, count: int = 20, queue: int = 420) -> list[str]:
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        _, data = self._get(url, params={"count": count, "queue": queue})
        return list(data)

    def match(self, match_id: str) -> tuple[str, dict]:
        """Full match payload. Returns (raw_text_exactly_as_received, parsed)."""
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        return self._get(url)
