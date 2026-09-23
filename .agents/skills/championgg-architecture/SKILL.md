---
name: championgg-architecture
description: Implement or review Champion.GG ingestion, Gold publication, API queries, frontend data loading, or container changes while preserving Python ownership, read-only serving, and Riot/demo isolation.
---

# Champion.GG architecture

Use this skill in the Championggrevitalizatoin repository. Locate the repository
root before resolving code paths. Read [AGENTS.md](../../../AGENTS.md) and
[codex.md](../../../codex.md), then the wiki pages relevant to the task:

| Change | Read |
|---|---|
| Ownership, upstream loading, storage, or a design review | [Architecture and boundaries](../../../docs/wiki/architecture.md) |
| Normalization, public fields, snapshots, or recovery | [Gold publication](../../../docs/wiki/publication.md) |
| Endpoints, rates, source/patch selection, or browser metadata | [API and frontend](../../../docs/wiki/api-and-ui.md) |
| Startup, credentials, mounts, or processor commands | [Operations](../../../docs/wiki/operations.md) |
| Implementation checks or schema documentation | [Development](../../../docs/wiki/development.md) |

These links assume this skill's repository location:
`.agents/skills/championgg-architecture/`. Keep the wiki as the detailed reference;
verify relevant claims against current code before making changes.

## Preserve the established boundaries

- Python owns upstream JSON ingestion, Bronze/Silver processing, aggregation,
  and Gold publication. Use the shared Data Dragon helper and canonical
  `processor.rebuild.rebuild` path; do not introduce TypeScript ingestion,
  request-triggered rebuilds, or a second publisher.
- The API reads only the separate Gold publication directory. Keep
  `DatabaseSync(..., { readOnly: true })`, exact schema validation, and no private
  database access or legacy-table fallback. Browser JSON comes from local API
  endpoints; Riot CDN image URLs remain allowed.
- Gold is a fresh SQLite database containing only the explicit public tables
  and columns. Raw payloads, player identities, private paths, and processing
  logs remain private. Do not publish a copy of the private database.
- Validate and close each immutable snapshot in rollback journal mode before
  atomically replacing `current.json`. Preserve the prior publication on build
  failure, the last valid reader on adoption failure, and JSON `503` when no
  valid snapshot exists. Keep all queries in one request on one snapshot.
- Preserve source through aggregate keys, joins, nested results, and rate
  denominators. Default to eligible Riot, then demo, then null; an explicitly
  selected empty source stays empty. Search/static data is shared. Preserve UI
  empty states and stale-response protection when changing data loading.
- Only Python receives private storage and Riot credentials. The API receives
  Gold read-only in Compose. A read-only connection alone is not proof of
  container isolation; do not replace this design with SQL accounts/grants.

## Apply a change

Trace the requested field or behavior through its owner and consumers. If an
endpoint needs data absent from Gold, extend the Python transform/publication
and then the API contract. Response formatting and rates over Gold aggregates
belong in TypeScript; upstream acquisition and raw-data aggregation do not.

For public schema changes, coordinate `processor/gold.py`, its SQL producers,
`webapp/server/src/snapshots.ts`, queries, types, and fixtures. Account for version
compatibility; the current reader explicitly accepts schema version 1. If making
request handling asynchronous, preserve snapshot lifetime for in-flight work
before changing adoption or connection cleanup.

Use the development guide's relevant checks. Add real HTTP coverage for each new
endpoint, fixtures with overlapping Riot/demo identifiers for source-sensitive
changes, and failure/adoption checks for publication changes. Test frontend
selection, optional metadata, and stale results when those paths change. Run
actual Docker checks for mount/credential changes and report unavailable Docker
as unverified. Do not run ingestion against the user's private data merely to
validate a documentation edit.

For any database definition change, including temporary views, follow `codex.md`:
update the schema reference and renderer, regenerate HTML/SVG, and update affected
diagrams/imports. Update the corresponding wiki pages when architecture or
behavior changes. Preserve existing data and unrelated workspace edits.

These are the current project decisions, not authority over an explicit user
redesign. When the user changes a boundary, carry that change through the code,
wiki, skill, and checks. Routine work within the boundaries needs no additional
approval workflow.
