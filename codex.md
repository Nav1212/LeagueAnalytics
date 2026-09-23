# Repository instructions

Start with [AGENTS.md](AGENTS.md) for the architecture boundaries and the
[architecture wiki](docs/wiki/README.md) for implementation and operations.
The schema maintenance requirements below remain applicable.

Whenever you change the database, update the visual schema in
[docs/database-snowflake-schema.html](docs/database-snowflake-schema.html) and
[docs/database-snowflake-schema.svg](docs/database-snowflake-schema.svg), along
with the [schema reference](docs/database-snowflake-schema.md), in the same
change. Regenerate the visuals with `python docs/render_database_schema.py`;
update the layout in that script when adding or removing objects, and the viewer
template if its presentation changes. This includes changes to tables, columns, types, keys,
constraints, relationships, indexes, migrations, and **any views**, including
temporary views. Keep the diagrams, table grains, storage locations, and view
definitions/dependencies aligned with the implementation. Update affected schema
diagrams and import files elsewhere in `docs/` as well; label proposed structures
separately from implemented ones.
