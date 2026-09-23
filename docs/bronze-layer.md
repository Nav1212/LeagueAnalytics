# League bronze layer

The bronze layer is a lossless landing zone. It stores source response bodies
before applying champion-statistics rules, so future silver models can be
rebuilt without calling Riot again.

## Lucidchart ERD import

Use [bronze-data-model-lucidchart.tsv](bronze-data-model-lucidchart.tsv) for a
Bronze-only diagram. In Lucidchart's Entity Relationship shape library, select
**Import > SQL Server**, proceed to the query-results step, and upload the TSV
or paste its full contents, including the header. Drag the imported tables onto
the canvas. See [Lucid's import instructions](https://help.lucid.co/hc/en-us/articles/16471565238292-Create-an-Entity-Relationship-Diagram-in-Lucidchart).

The file describes the five active Bronze tables from `processor/db.py`, with
their primary keys, declared foreign keys, and the compound payload uniqueness
constraint. It uses SQL Server metadata formatting for import; the application
still uses SQLite. Integer columns display as `bigint` and text columns as `text`.
This is diagram metadata, not an executable SQL Server schema.

`bronze_fetch_runs` connects to `bronze_payloads` and `bronze_fetch_errors` through
`fetch_run_id`. Matches and timelines share `match_id` logically, but the current
schema does not declare that foreign key, so the import does not invent one.
An optional manual connector can show that logical relationship. The legacy
`raw_matches` migration table is excluded from this active-layer diagram.

## Storage contract

| Table | Grain | Purpose |
|---|---|---|
| `bronze_fetch_runs` | One ingestion invocation | Parameters, lifecycle, and completion state |
| `bronze_fetch_errors` | One failed request | Dataset/key-level gaps in partial pulls |
| `bronze_payloads` | One distinct payload version per source/dataset/routing/key | Exact response body and request provenance |
| `bronze_matches` | One Match-V5 match ID | Efficient canonical input for match silver jobs |
| `bronze_match_timelines` | One Match-V5 match ID | Efficient canonical input for timeline silver jobs |

`bronze_payloads.response_json`, `bronze_matches.json`, and
`bronze_match_timelines.json` are not reshaped. `content_sha256` deduplicates
byte-identical refreshes while retaining changed resource versions. API keys
are sent in headers and are never stored in URLs, parameters, or payload rows.

The old `raw_matches` table is retained only as a migration source. On schema
initialization, its rows are copied into `bronze_matches` with `INSERT OR
IGNORE`; all active ingestion and aggregation uses `bronze_matches`.

## Dataset catalog

One `fetch` run covers the following standard, read-only League datasets.

| Source family | Bronze datasets |
|---|---|
| Account-V1 | `account-v1.account` |
| Champion-Mastery-V4 | `champion-mastery-v4.masteries`, `champion-mastery-v4.score` |
| Champion-V3 | `champion-v3.rotation` |
| Clash-V1 | `clash-v1.tournaments` |
| League-V4 | `league-v4.apex-league`, `league-v4.entries` |
| League-EXP-V4 | `league-exp-v4.entries` |
| LoL-Challenges-V1 | `lol-challenges-v1.config`, `lol-challenges-v1.percentiles`, `lol-challenges-v1.player-data` |
| LoL-Status-V4 | `lol-status-v4.platform-data` |
| Match-V5 | `match-v5.match-ids`, `match-v5.match`, `match-v5.timeline` |
| Spectator-V5 | `spectator-v5.featured-games`, `spectator-v5.active-game` |
| Summoner-V4 | `summoner-v4.summoner` |
| Data Dragon | versions, languages, realm, champion summary/details, items, summoner spells, runes, profile icons, maps |
| Riot static reference data | seasons, queues, maps, game modes, game types |

The pull intentionally does not invoke:

- Tournament-V5/Tournament-Stub-V5 mutation workflows, which create and
  administer tournaments and require separate product authorization.
- LoL-RSO-Match endpoints, which require production RSO and player opt-in.
- Local League Client, Live Client Data, and Replay APIs, which are exposed by
  a running game client rather than Riot's server API.

Those sources can still use the same `bronze_payloads` contract when their
credentials and execution environments are introduced.

## Pull behavior

```powershell
$env:RIOT_API_KEY = "RGAPI-..."
python -m processor.main fetch `
  --platform na1 `
  --region americas `
  --league-pages 1 `
  --players 50 `
  --per-player 20 `
  --max 500
```

For a static-only localized refresh, use for example
`python -m processor.main sync-static --locale fr_FR --realm euw`.

The fetcher:

1. Lands Data Dragon and Riot reference data.
2. Lands platform-wide rotation, status, challenge, spectator, and Clash data.
3. Lands apex leagues and configured pages for every other ranked tier.
4. Samples PUUIDs across those ladder responses.
5. Lands account, summoner, mastery, challenge, and active-game responses.
6. Discovers recent match IDs across queues and lands both matches and timelines.
7. Marks the fetch run `complete`, `partial`, or `failed`.

Use `--no-static`, `--no-player-data`, or `--no-timelines` only for targeted
refreshes. Increase `--league-pages` to widen lower-tier sampling. A successful
active-game lookup is stored; a Spectator 404 simply means the sampled player
is not currently in a game and is not considered an error.

## Silver boundary

The Python processor normalizes Bronze into private Silver tables, validates the
result, and publishes a separate Gold-only SQLite snapshot for the API. See the
[current schema reference](database-snowflake-schema.md). The older
[Silver layer plan](silver-layer-plan.md) is a historical proposal.
Rebuild and publish with:

```powershell
python -m processor.main aggregate
```

Timeline-, rank-, player-, and static-data silver models should read the latest
appropriate version from `bronze_payloads` or the keyed Match-V5 tables. Bronze
must not embed business rules such as minimum sample size, role eligibility,
tier grouping, or win-rate calculation.
