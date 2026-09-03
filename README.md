# Champion.GG Revitalization

A champion.gg-style League of Legends stats service: win / pick / ban rates,
matchups, builds, spells and runes per champion, role and patch.

```
Riot API ──> Python processor ──> SQLite ──> TypeScript server ──> React frontend
             (fetch + aggregate)   (raw +      (Express, read-only)  (Vite, hextech UI)
                                    aggregates)
```

## Architecture

| Piece | Tech | Path |
|---|---|---|
| Data processor | Python 3.12, `requests` | [processor/](processor/) |
| Database | SQLite (raw layer + aggregate layer) | `data/champions.db` (generated) |
| API server | TypeScript on Node 24 (`node:sqlite`, Express) — runs `.ts` directly, no build step | [webapp/server/](webapp/server/) |
| Frontend | React 19 + TypeScript + Vite | [webapp/client/](webapp/client/) |

**The raw layer mirrors the Riot API exactly.** Every row in `raw_matches`
stores the unmodified Match-V5 response body, byte for byte. The aggregate
tables (champion_stats, matchups, builds, spell_sets, rune_sets, …) are
derived from it and can be wiped/rebuilt at any time with
`python -m processor.main aggregate`. More complex modeling later plugs in at
that same spot without touching ingestion.

## Quick start

```powershell
# 1. one-time setup
python -m pip install -r requirements.txt
npm install

# 2. populate the database (no API key needed — synthetic matches in exact
#    Match-V5 shape, champions/identity pulled live from Data Dragon)
python -m processor.main seed

# 3. build the frontend and start the server
npm run build
npm run start        # -> http://localhost:8000
```

### Development mode (hot reload)

```powershell
npm run dev:server   # API on :8000 (node --watch)
npm run dev:client   # Vite on :5173, proxies /api -> :8000
```

## Using real Riot data

Get a (free) development key from https://developer.riotgames.com, then:

```powershell
$env:RIOT_API_KEY = "RGAPI-..."
python -m processor.main fetch --max 500 --platform na1 --region americas
python -m processor.main purge-demo    # optional: drop the synthetic rows
```

The fetcher walks the challenger/GM/master ladder, pulls recent ranked-solo
matches per player, and stores each response verbatim. It paces itself to dev
key limits (100 requests / 2 min) and honors 429 Retry-After.

### Processor commands

```
python -m processor.main seed [--matches N]   seed demo data + aggregate
python -m processor.main fetch [--max N]      fetch real matches + aggregate
python -m processor.main aggregate            rebuild aggregates from raw
python -m processor.main purge-demo           remove demo rows, re-aggregate
python -m processor.main status               show what's in the database
```

## API

| Endpoint | Description |
|---|---|
| `GET /api/meta` | patches, match counts, ddragon version, data sources |
| `GET /api/champions?patch=16.17` | per champion+role: win/pick/ban rate, KDA, CS, games |
| `GET /api/champion/:key?patch=16.17` | full detail: per-role stats, matchups, core builds, spells, runes |
| `GET /api/search?q=ahri` | champion name search |

## Notes

- Champion/item/spell/rune images are hotlinked from Riot's Data Dragon CDN
  (no key required); the UI degrades gracefully offline.
- Skill orders need Match-V5 *timeline* payloads — planned for the raw layer
  later, along with rank-tier filtering and proper confidence modeling.
- Not affiliated with Riot Games.
