# Development and future runs

[Wiki home](README.md) | [Architecture boundaries](architecture.md)

## Locate a change

| Requested change | Implementation path | Boundaries to check |
|---|---|---|
| New upstream or static dataset | Python ingestion helpers, Bronze recording, typed staging, Silver models | Exact payload lineage stays private; retain shared Data Dragon loading |
| New aggregate or public field | Python Gold SQL and explicit publication schema, then API queries/types | Publish only necessary public data; keep source keys and denominators |
| New endpoint or query | TypeScript route and repository, client types if consumed | Read only Gold, acquire one request repository, add real HTTP coverage |
| New browser metadata | Python ingestion/publication, local API endpoint, frontend mapping | Initialize optional maps before rendering; browser JSON stays local |
| Source/patch interaction | App context and Home/Champion loading effects | Retain supported patch, handle empty data, reject stale responses |
| Deployment/storage change | Compose, Dockerfiles, configuration docs | Only Python sees private storage and the Riot key; web Gold mount remains read-only |

If a field is unavailable in Gold, extend Python's publication contract rather
than opening the private database from the API. The API can compute presentation
rates from published aggregates; it must not rebuild aggregates from raw data.
Preserve unrelated worktree changes and private datasets while making changes.

## Contract evolution

Changes to published objects must update [gold.py](../../processor/gold.py) and
the exact table/column checks in [snapshots.ts](../../webapp/server/src/snapshots.ts),
plus SQL producers, query consumers, fixtures, and affected response types. For a
format/version change, make producer/reader compatibility deliberate: a reader
that does not support the new version retains its last loaded valid snapshot,
but a fresh reader has no cached fallback.

Every statistics join must preserve `source`, especially joins where Riot/demo
fixtures use the same champion, match, patch, role, or item identifiers. Test
with overlapping identifiers and different results so accidental mixing is
observable. Do not use legacy private aggregates as a compatibility path.

## Verification commands

Run commands from the repository root with the Python environment activated.
Choose checks matching the changed behavior; documentation-only edits need link
and content validation rather than a full rebuild of user data.

| Command | Evidence |
|---|---|
| `python -m unittest discover -s processor -t .` | Bronze provenance/migration, typed transforms, publication allowlist, source separation, optional static data, failure retention, and cleanup |
| `npm run test:server` | Node's test runner, real HTTP server on an ephemeral port, temporary Gold databases built with the production schema and Python publisher |
| `npm run test:client` | Playwright source/patch selection, empty states, rune fallback, and stale-response handling |
| `npm run typecheck --workspace webapp/client` | Client TypeScript types |
| `npm run typecheck --workspace webapp/server` | Server TypeScript types |
| `npm run build` | Both type checks and the frontend production build |
| `python scripts/test_containers.py` | Real container endpoints, private storage/credential isolation, and read-only mount |
| `python docs/render_database_schema.py` | Regenerated schema HTML, SVG, and Gold diagram/import artifacts |

Endpoint fixtures are deterministic and need no upstream requests or Riot key.
The suite discovers `.venv` Python when present; set `PYTHON` to override it.
Python rebuild tests need the SQLite extension installed by `setup` first.
Browser tests use installed Edge on Windows; elsewhere install Playwright
Chromium (`npx playwright install chromium`). `PLAYWRIGHT_CHANNEL` can select
another installed browser. Browser tests use local API fixtures and block
external assets.

New endpoints need integration tests covering success, relevant source/patch
behavior, empty results, and errors. Publication changes must exercise failed
publication preserving results and successful publication becoming visible
without restarting the API. Report a missing Docker runtime as an unverified
container check, not as a pass.

## Documentation maintenance

[codex.md](../../codex.md) requires every database change to update the schema
reference, HTML/SVG diagrams, and affected diagrams/imports in the same change.
This includes temporary views, columns, types, keys, constraints, relationships,
indexes, and migrations. Update [the renderer](../render_database_schema.py) and
its layout when needed, then regenerate; do not edit generated files alone.
Keep historical proposals labeled separately from the implemented schema.

Update the affected wiki pages whenever ownership, publication, API behavior,
configuration, or validation commands change. Link to schema/code definitions
instead of maintaining a second exhaustive column reference here.

## Guidance for agents

[AGENTS.md](../../AGENTS.md) is the repository entry point and links the existing
schema maintenance rules. The
[championgg-architecture skill](../../.agents/skills/championgg-architecture/SKILL.md)
provides a short change workflow and directs agents to the relevant wiki pages.
It is stored under the repository's `.agents/skills` directory so it travels with
the project; automatic selection remains enabled. This follows the documented
[repository skill discovery](https://learn.chatgpt.com/docs/build-skills) and
[AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
mechanisms.

Explicit invocation examples:

```text
Use $championgg-architecture to add a source-scoped statistics endpoint.
Use $championgg-architecture to review this data-loading change.
```

The skill should guide a future implementation without requiring conversation
history. It applies to this project's data, API, UI loading, and deployment
contracts, not unrelated repositories. A user-authorized architecture change
should update the documented boundary and its tests; routine work within these
boundaries does not require an extra approval step.
