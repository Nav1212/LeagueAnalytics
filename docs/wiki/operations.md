# Operations

[Wiki home](README.md) | [Development and checks](development.md)

## Local startup

From the repository root, use Python 3.12 and Node 24. Activate the Python
environment before these commands. On PowerShell systems that block `npm.ps1`,
use `npm.cmd` in place of `npm`.

```powershell
python -m pip install -r requirements.txt
npm ci
python -m processor.main setup
```

Publish from existing private data with `python -m processor.main aggregate`.
For a fresh demo installation, use `python -m processor.main seed` instead. Demo
seeding refreshes champion/rune metadata through the shared Python loader;
offline operation retains cached metadata or falls back to bundled champions.

After the first successful publication:

```powershell
npm run build
npm run start
# http://localhost:8000
```

Development uses `npm run dev:server` and `npm run dev:client` in separate
terminals. Vite on port 5173 proxies API requests to port 8000.

## Configuration

| Variable | Owner | Behavior |
|---|---|---|
| `CHAMPIONGG_DB` | Python | Private SQLite file; default is the repository's `data/champions.db`. A supplied relative path is relative to the process working directory |
| `CHAMPIONGG_GOLD_DIR` | Python and API | Shared publication directory; default `data/gold`. Relative values resolve against the repository root in both services |
| `RIOT_API_KEY` | Python only | Credential for Riot ingestion; never passed to the web service or client build |
| `PORT` | API | Local listening port, default 8000; tests use 0 for an ephemeral port |
| `CHAMPIONGG_PORT` | Compose | Host port, default 8000; the container still listens on 8000 |

Use absolute private paths when launching Python from outside the repository.
[.env.example](../../.env.example) provides examples. Compose reads `.env`; the
local Python and Node entry points do not automatically load it. Compose sets
its database paths explicitly; changing the local `CHAMPIONGG_DB` variable does
not mount that file into a container.

## Container deployment

```powershell
docker compose build processor api
docker compose run --rm processor seed
docker compose up -d api
```

The processor image installs its prerequisites and DuckDB extension at build
time. It is in the `tools` profile and is run explicitly for commands, rather
than started as a daemon by `compose up`. The API serves the built frontend.

[compose.yaml](../../compose.yaml) uses `private-data` and `gold-data` named
volumes. Python mounts both read-write. TypeScript mounts only `gold-data`,
read-only, and receives no Riot key. The default published port binds to host
loopback (`127.0.0.1`).

Named volumes start separately from local `data/`. To reuse existing local
storage, configure the processor's private mount to that directory, keep the
Gold mount separate, and run `aggregate` before starting the API. Do not mount
the whole `data/` directory into the API. Keep the original private data; the
migration does not require deleting it or dropping legacy tables.

## Refresh and diagnosis

| Command (`python -m processor.main ...`) | Use |
|---|---|
| `setup` | Provision the extension before offline rebuilds |
| `aggregate` | Rebuild and publish existing private inputs |
| `seed --matches N` | Generate demo inputs, refresh static metadata, and publish |
| `fetch --max N --platform na1 --region americas` | Ingest Riot inputs and publish; requires the key in Python's environment |
| `sync-static` | Refresh static/reference inputs and republish |
| `purge-demo` | Intentionally delete demo match rows and their legacy copies, then republish; not a startup or repair step |
| `status` | Inspect private counts and the public manifest locally; its output is not public API data |

Compose runs the same commands as `docker compose run --rm processor <command>`.

| Symptom | Check and response |
|---|---|
| JSON `503` before any data is served | Check Gold directory configuration, manifest, readable snapshot, and compatible schema; publish a valid first snapshot with Python |
| API still serves old results after a rebuild | Inspect the private run report and API logs; a failed build or rejected candidate intentionally preserves the previous publication |
| `partial` rebuild | Inspect `silver_quality_issues` in the private DuckDB run; correct the inputs/normalization, then rebuild without disabling validation |
| Extension unavailable | Run `setup` with network access; do not add extension downloads to request handling or rebuilds |
| Older Gold files remain | An open reader may defer cleanup; a later publication retries it. Do not modify the current snapshot in place |
| Missing runes | Check the requested version and `en_US` catalog; an absent catalog returns empty styles, while the UI retains optional-data fallbacks |
| Rebuild runs out of memory | Inspect private `report.json` resource measurements. The Python `rebuild()` function supports `threads`, `memory_limit`, and `spill_directory`; the main CLI does not expose these options yet |

## Deployment verification

`python scripts/test_containers.py` requires Docker with Compose. It builds a
unique disposable project, publishes fixtures, checks all endpoints, and checks
that the API cannot see private storage or credentials or write Gold. Cleanup
removes only that test project's volumes.

Docker was unavailable during the initial implementation verification. Container
configuration exists, but runtime isolation must be verified in a Docker-capable
environment; local read-only database tests do not prove the mount boundary.
