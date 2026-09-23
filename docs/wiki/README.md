# Architecture wiki

Champion.GG uses one Python processor to ingest and transform data, then publish
Gold SQLite snapshots. The TypeScript API and React frontend consume those
snapshots. This wiki describes the implemented architecture and the boundaries
future changes must preserve.

| Page | Read it for |
|---|---|
| [Architecture and boundaries](architecture.md) | Ownership, data flow, isolation, and why the services are separate |
| [Gold publication](publication.md) | Storage contract, validation, atomic switching, and recovery |
| [API and frontend](api-and-ui.md) | Endpoints, source selection, statistics, and browser data loading |
| [Operations](operations.md) | Local and container startup, configuration, existing data, and troubleshooting |
| [Development](development.md) | Change locations, tests, schema documentation, and guidance for future agents |

The [root README](../../README.md) is the quick start. Detailed table definitions
remain in the [schema reference](../database-snowflake-schema.md),
[interactive diagram](../database-snowflake-schema.html), and
[SVG diagram](../database-snowflake-schema.svg). The [Bronze catalog](../bronze-layer.md)
describes ingestion datasets and provenance.

The [older Silver plan](../silver-layer-plan.md) and
[proposed Silver diagram](../silver-core-proposed.mmd) are historical proposals.
Use current code and the schema reference to establish what exists today.

For agent-assisted changes, start with [AGENTS.md](../../AGENTS.md) and the
[championgg-architecture skill](../../.agents/skills/championgg-architecture/SKILL.md).
Keep this wiki with the code; it does not require a separate hosted wiki service.
