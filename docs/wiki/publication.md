# Gold publication

[Wiki home](README.md) | [Architecture](architecture.md)

## Canonical processing path

`aggregate` calls `processor.rebuild.rebuild`. The rebuild stages of `seed`,
`fetch`, `purge-demo`, and `sync-static` use the same path. `setup` provisions the
DuckDB SQLite extension separately; rebuilds do not download extensions.

1. Acquire the private database writer lock and capture the input tables in a
   consistent SQLite transaction.
2. Load that capture into a fresh DuckDB run, parse typed staging records, build
   Silver models, and compute the Gold aggregates.
3. Check quality issues, model keys/references, aggregate keys, and input/output
   reconciliation. Error or pending issues produce a `partial` run and prevent
   publication. Exceptions produce a `failed` run.
4. For a validated run, invoke the Gold publisher. Keep processing reports and
   executed SQL in the private run directory.

Typed parsing permits missing optional fields as nulls while rejecting
incompatible provided values. It must not silently turn malformed nested data
into valid empty records. Static normalization retains rune and style icon paths.

## Public schema

[processor/gold.py](../../processor/gold.py) defines the production SQLite schema
and explicit publication allowlist. Current schema version: **1**.

| Table | Public content / key |
|---|---|
| `gold_patch_totals` | Eligible match count by `(source, patch)` |
| `gold_champion_stats` | Summed statistics by `(source, patch, champion_id, role)` |
| `gold_champion_bans` | Bans by `(source, patch, champion_id)` |
| `gold_matchups` | Opponent results by source, patch, champion, role, and opponent |
| `gold_builds` | Item combinations by source, patch, champion, role, and items |
| `gold_spell_sets` | Spell combinations by source, patch, champion, role, and spells |
| `gold_rune_sets` | Rune choices by source, patch, champion, role, keystone, and secondary style |
| `gold_champions` | Public champion identity, title, and tags; keyed by champion ID |
| `gold_source_counts` | Raw keyed match counts per source; distinct from eligible match counts |
| `gold_rune_catalog` | Complete styles/slots/runes JSON by `(version, locale)`, including names and icons |
| `gold_meta` | `ddragon_version` when available, plus `schema_version`, `run_id`, and `aggregated_at` |

No raw match/player payloads, player identities, private filesystem paths, or
processing logs are part of this contract. The publisher selects named columns
into a new database; it does not export all tables or all private metadata.

Rune catalogs use the latest observed complete payload for each version and
locale. Picking the latest individual styles could incorrectly retain styles
removed by a newer payload. Re-observing an older deduplicated payload can make
that complete catalog current again.

## Commit protocol

Publication is serialized by `.publish.lock` in `CHAMPIONGG_GOLD_DIR`.

1. Build a temporary SQLite file with the production schema and selected values.
2. Commit, run SQLite integrity validation, and close it in `DELETE` rollback
   journal mode. Serving requires no WAL or SHM sidecars.
3. Rename the completed file to `gold-<run_id>.sqlite` without overwriting an
   existing run ID.
4. Write and flush a temporary manifest, then atomically replace `current.json`.
   **The manifest replacement is the publication commit point.**
5. Retain the new current and previously current snapshot. Remove older generated
   snapshots on a best-effort basis; a file held open on Windows can survive
   until a later publication retries cleanup.

Example manifest shape (illustrative values):

```json
{
  "snapshot": "gold-example-run.sqlite",
  "schemaVersion": 1,
  "runId": "example-run",
  "publishedAt": "2026-09-22T12:00:00+00:00"
}
```

Completed snapshots are immutable. A failed build leaves the manifest unchanged.
A failure between snapshot rename and manifest replacement can leave an orphan
snapshot, but it does not become active. Do not update a published database in
place or make the API create a missing database.

## API adoption and recovery

[GoldSnapshots](../../webapp/server/src/snapshots.ts) reads the manifest between
requests. Before switching it checks the manifest version and run ID, resolves
the snapshot inside the publication directory, and opens it read-only. It
validates the exact public table/column inventory, SQLite version marker,
integrity, rollback journal mode, and matching public run/schema metadata.

Only a valid candidate replaces the active connection. A failed replacement
keeps the last valid connection and logs the failure. Without any valid snapshot,
data endpoints return JSON `503`.

Each route acquires one repository, then performs its queries synchronously
against that connection. This keeps metadata, totals, and nested results in a
single response on the same snapshot. Separate HTTP requests may legitimately
observe different publications. Introducing asynchronous database work requires
preserving request ownership before changing connection lifetime or closing old
snapshots.

Publication format changes must coordinate the Python schema and metadata with
the TypeScript manifest/schema validator, fixtures, and consumers. A version bump
alone does not add compatibility: the current reader accepts only version 1.
See [development](development.md) for the required validation and documentation.
