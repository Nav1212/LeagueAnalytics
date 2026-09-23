# Champion.GG repository guidance

Read [codex.md](codex.md) for the schema documentation rules. The maintained
architecture overview is the [wiki](docs/wiki/README.md).

For changes to ingestion, storage, publication, API queries, frontend data
loading, source selection, or deployment, read and apply
[championgg-architecture](.agents/skills/championgg-architecture/SKILL.md).
Read only the wiki pages relevant to the task.

Preserve these established boundaries unless the user explicitly changes them:

- Python alone ingests upstream JSON, transforms private Bronze/Silver data,
  and publishes Gold through the validated DuckDB rebuild.
- TypeScript reads only published Gold snapshots through a read-only connection.
  Private database access, legacy-table fallbacks, and migrations do not belong
  in the API. The browser loads JSON from the local API; CDN images remain allowed.
- Publish fresh Gold-only files and atomically switch the manifest. Retain the
  last valid snapshot on failure and keep each request on one snapshot.
- Keep Riot/demo sources separate through keys, joins, nested results, and rate
  denominators. Static/search data stays source-independent.
- Only Python receives private storage and Riot credentials. The API's Gold
  container mount stays read-only.

Use the [development guide](docs/wiki/development.md) for change locations and
checks. New endpoints need real HTTP integration coverage. Preserve existing
private data and unrelated worktree changes. When an authorized change alters
a boundary, update the wiki, skill, and relevant checks with the implementation.
