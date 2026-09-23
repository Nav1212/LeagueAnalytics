# API and frontend

[Wiki home](README.md) | [Gold publication](publication.md)

The current API is Express 5 running TypeScript directly on Node 24, with
`node:sqlite` for read-only Gold queries. The contract lives in
[route handlers](../../webapp/server/src/index.ts),
[repository queries](../../webapp/server/src/db.ts),
[client types](../../webapp/client/src/api.ts), and
[endpoint integration tests](../../webapp/server/test/api.integration.test.ts).
There is currently no checked-in OpenAPI specification or generated OpenAPI
server/client; do not assume one exists when changing endpoints.

## Routes

| GET endpoint | Parameters | Result |
|---|---|---|
| `/api/meta` | Optional `source=riot\|demo` | Selected/available sources, numerically ordered patches, counts, Data Dragon version, publication metadata |
| `/api/champions` | Optional source and patch | `{ source, patch, rows }` for qualifying champion/role samples |
| `/api/champion/:key` | Optional source and patch | Case-insensitive champion key or name lookup; source, patch, role statistics, matchups, builds, spells, runes |
| `/api/search` | Optional `q` | Trimmed, case-insensitive name/key matching, name ordering, at most ten results; blank/no matches return `[]` |
| `/api/static/runes` | Optional `version` | `{ version, styles }` for `en_US`; defaults to the published Data Dragon version |
| `/` | None | Built frontend when available, otherwise the API landing response |

Invalid source values on the three source-aware endpoints return JSON `400`.
Unknown champions return JSON `404`; unavailable Gold returns JSON `503`;
unexpected data-handler errors return JSON `500` with `internal error`. A valid
empty publication is different from an unavailable publication.

## Cohorts and denominators

Available sources come from Gold patch totals with eligible matches. An omitted
source selects Riot when available, otherwise demo, otherwise `null`. An explicit
valid source remains selected even when it has no data; responses are empty
rather than silently falling back to another cohort. Search and static metadata
are source-independent.

Omitted patch selects the selected source's latest patch. Patch ordering is
numeric (`16.10` after `16.9`). A known champion without data for the chosen
source/patch returns its identity with empty roles, rather than an unknown
champion error.

Gold eligibility currently requires queue `420` and duration at least 300 seconds.
Champion statistics additionally require a normalized role and positive champion
ID. Every statistics query and join includes source, including ban joins,
opponents, builds, spells, and runes. In each selected source/patch:

- Win rate uses wins / games; pick rate uses champion-role games / eligible
  matches; ban rate uses bans / eligible matches. Rates are percentages rounded
  to one decimal place.
- The champion list requires at least `max(10, round(matches * 0.008))` games and
  orders by champion name, then games descending. The UI may apply another sort.
- Detail matchups require three games. Build candidates require three games and
  use the forty most frequent combinations; each displayed build list has at
  most five entries. Spell and rune lists have at most three entries each.
- Builds describe sorted combinations from the first three eligible final
  inventory slots, not chronological purchase order. Timeline-based purchase or
  skill-order analysis would be a new Python-derived feature.

`meta.totalMatches` and `meta.patches` describe the selected cohort.
`meta.rawMatches` intentionally summarizes both stored sources, and
`meta.championCount` counts the shared identity catalog. Raw counts are not a
statistics denominator or proof that a source has eligible data.

## Frontend loading

[App.tsx](../../webapp/client/src/App.tsx) loads metadata, then the local rune
endpoint, and initializes the rune maps before rendering statistics. Missing or
malformed optional rune data falls back to bundled names/icons. Images continue
to use Riot CDN URLs; do not restore a browser fetch of external rune JSON.

The source selector sits beside the patch selector and lists available sources.
Switching source reloads metadata and statistics, retains a patch available in
the new source, and otherwise selects the latest patch. When no matches exist,
the home page shows an explicit empty state and disabled selectors.

App, Home, and Champion use abort signals and stale-response checks. Old source,
patch, or champion requests must not overwrite a newer selection. These rules
apply to nested detail results as well as the main champion list. The browser
suite in [sources.spec.ts](../../webapp/client/test/sources.spec.ts) exercises
selection, empty states, optional rune failures, and late response handling.
