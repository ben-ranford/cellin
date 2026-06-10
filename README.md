# cellin

[![PyPI Version](https://img.shields.io/pypi/v/cellin)](https://pypi.org/project/cellin/)
[![Release Passing](https://github.com/ben-ranford/cellin/actions/workflows/release.yml/badge.svg)](https://github.com/ben-ranford/cellin/actions/workflows/release.yml)

Cellin builds long-lived multimodal memory, dreams over it to consolidate ideas, and
retrieves context with transparent weighted ranking.

## Install

From source today:

```bash
git clone https://github.com/ben-ranford/cellin.git
cd cellin
make bootstrap
```

Install from [PyPI](https://pypi.org/project/cellin/):

```bash
python3 -m pip install cellin
```

## Run as MCP server

Cellin can run as an MCP stdio server for clients such as Claude Desktop and
Cursor:

```bash
python3 -m pip install "cellin[mcp]"
cellin mcp serve --check
cellin mcp serve
```

The Docker image starts the same stdio server by default:

```bash
make docker-build
docker run -i --rm -v cellin-data:/data cellin-mcp:latest
```

Environment variables select packaged storage presets:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CELLIN_BACKEND` | `sqlite` | `sqlite`, `postgres`, `neo4j`, or `in_memory` |
| `CELLIN_DATA_DIR` | `/data` | SQLite subject database and subject index directory |
| `CELLIN_CONNECTION_STRING` | unset | PostgreSQL DSN or Neo4j bolt URL for remote presets |

For PostgreSQL:

```bash
docker run -i --rm \
  -e CELLIN_BACKEND=postgres \
  -e CELLIN_CONNECTION_STRING="$CELLIN_POSTGRES_DSN" \
  cellin-mcp:latest
```

For Neo4j:

```bash
docker run -i --rm \
  -v cellin-data:/data \
  -e CELLIN_BACKEND=neo4j \
  -e CELLIN_CONNECTION_STRING="$CELLIN_NEO4J_URI" \
  cellin-mcp:latest
```

`docker-compose.yml` includes a single-container SQLite service and profiled
PostgreSQL and Neo4j variants:

```bash
docker compose up --build cellin-sqlite
CELLIN_POSTGRES_PASSWORD="$CELLIN_POSTGRES_PASSWORD" \
CELLIN_POSTGRES_DSN="$CELLIN_POSTGRES_DSN" \
  docker compose --profile postgres up --build cellin-postgres
CELLIN_NEO4J_AUTH="$CELLIN_NEO4J_AUTH" \
CELLIN_NEO4J_URI="$CELLIN_NEO4J_URI" \
  docker compose --profile neo4j up --build cellin-neo4j
```

Claude Desktop configuration:

```json
{
  "mcpServers": {
    "cellin": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "cellin-data:/data", "cellin-mcp:latest"]
    }
  }
}
```

## Quickstart

From the repository root:

```bash
WORKSPACE=.cellin-workspace
python3 -m uv run cellin init --workspace "$WORKSPACE"
python3 -m uv run cellin storage list --role memory
python3 -m uv run cellin storage init --config "$WORKSPACE/cellin.json" --dry-run
python3 -m uv run cellin ingest --config "$WORKSPACE/cellin.json" --input examples/starter/seed_envelopes.json
python3 -m uv run cellin retrieve --config "$WORKSPACE/cellin.json" --query "memory graph retrieval" --top-k 2
python3 -m uv run cellin dream --config "$WORKSPACE/cellin.json" --strategy abstraction
python3 -m uv run cellin eval run --suite smoke --config "$WORKSPACE/cellin.json" --output "$WORKSPACE/smoke.json"
python3 -m uv run cellin trace inspect --config "$WORKSPACE/cellin.json" --limit 5
```

See `examples/starter/README.md` for the same flow in a shorter checklist form.

Workspace config now supports role-specific storage backends:

```json
{
  "runtime_id": "cellin-cli",
  "trace_path": "traces.jsonl",
  "profile_name": "balanced",
  "storage": {
    "memory": { "backend": "in_memory" },
    "graph": { "backend": "in_memory" },
    "vector": { "backend": "in_memory_vector_index" },
    "representation": { "backend": "in_memory_vector_index" }
  }
}
```

`cellin init` now writes this in-memory-first preset by default.

Legacy workspaces that only define `database_path` continue to work and are migrated to this shape behind the scenes.

Use `cellin storage list` to inspect the built-in provider registry and any third-party providers
registered through the `cellin.storage` entry-point group. Run `cellin storage init --config
<workspace>/cellin.json` before first use when you want an explicit, idempotent setup step for
durable backends.

For an explicit SQLite preset, set:

```json
{
  "memory": { "backend": "sqlite", "database_path": "cellin.sqlite" },
  "graph": { "backend": "sqlite", "database_path": "cellin.sqlite" }
}
```

For additional SQL-backed presets, install optional dependencies as needed:

```bash
python3 -m pip install cellin[duckdb]
python3 -m pip install cellin[postgresql]
python3 -m pip install cellin[mysql]
python3 -m pip install cellin[sql-backends]
python3 -m pip install cellin[storage-backends]
```

Use `duckdb` to point both roles at a local DB file:

```json
{
  "memory": { "backend": "duckdb", "database_path": "cellin.duckdb" },
  "graph": { "backend": "duckdb", "database_path": "cellin.duckdb" }
}
```

Use `postgresql` and `mysql` with connection strings:

```json
{
  "memory": { "backend": "postgresql", "database_path": "postgresql://db.example.invalid:5432/db" },
  "graph": { "backend": "postgresql", "database_path": "postgresql://db.example.invalid:5432/db" }
}

{
  "memory": { "backend": "mysql", "database_path": "mysql://db.example.invalid:3306/db" },
  "graph": { "backend": "mysql", "database_path": "mysql://db.example.invalid:3306/db" }
}
```

For document and cache-oriented presets, install optional dependencies as needed:

```bash
python3 -m pip install cellin[mongodb]
python3 -m pip install cellin[redis]
python3 -m pip install cellin[document-cache-backends]
```

Use `mongodb` when you want durable document storage for both memories and edges:

```json
{
  "memory": { "backend": "mongodb", "database_path": "mongodb://db.example.invalid:27017/cellin" },
  "graph": { "backend": "mongodb", "database_path": "mongodb://db.example.invalid:27017/cellin" }
}
```

Use `redis` for low-latency cache-oriented deployments where operators control TTL or eviction:

```json
{
  "memory": { "backend": "redis", "database_path": "redis://host:6379/0" },
  "graph": { "backend": "redis", "database_path": "redis://host:6379/0" }
}
```

MongoDB stores whole memory and edge documents and preserves archived entries as tombstones in the
document payloads. Redis stores JSON payloads per key and also preserves archived entries as
tombstones, filtering them from neighbor and edge listing reads rather than hard-deleting them.

For graph-native backends, install the optional dependencies you need:

```bash
python3 -m pip install cellin[neo4j]
python3 -m pip install cellin[memgraph]
python3 -m pip install cellin[arangodb]
python3 -m pip install cellin[graph-backends]
```

Use `neo4j`, `memgraph`, or `arangodb` for the graph role while keeping memory storage separate if
you prefer:

```json
{
  "memory": { "backend": "sqlite", "database_path": "cellin.sqlite" },
  "graph": { "backend": "neo4j", "database_path": "bolt://graph.example.invalid:7687" }
}
```

Graph-native stores persist edge relationships plus graph-local memory payload snapshots. When
`GraphStore.get_memory()` is asked for a node that only exists as a placeholder created during edge
upserts, it returns `None` and retrieval falls back to the configured memory store as the source of
truth. That keeps mixed deployments working without caller changes while making the graph-local
snapshot behavior explicit.

For vector-backed retrieval stores, install the optional dependencies you need:

```bash
python3 -m pip install cellin[pgvector]
python3 -m pip install cellin[pinecone]
python3 -m pip install cellin[qdrant]
python3 -m pip install cellin[weaviate]
python3 -m pip install cellin[milvus]
python3 -m pip install cellin[redis-vector]
python3 -m pip install cellin[vector-backends]
```

Use `cellin storage init --config "$WORKSPACE/cellin.json"` after switching a workspace onto a
durable backend family so local files, schemas, or remote collection bootstrap happen explicitly
before ingest or retrieval.


## Primary surfaces

- CLI: `cellin init`, `storage list`, `storage init`, `ingest`, `retrieve`, `dream`, `plugin list`, `eval run`, `trace inspect`
- Ingestion: `cellin.ingest.ArtifactEnvelope` and `cellin.ingest.CanonicalIngestor`
- Retrieval: `cellin.retrieval.WeightedRetriever`, `cellin.retrieval.RetrievalCandidateGenerator`, and `cellin.ranking.WeightedRanker`
- Dreaming: `cellin.dreaming.DreamRunner` plus the built-in deduplication, abstraction, and contradiction-repair strategies
- Evals: `cellin.evals.run_evaluation_suite` and `cellin.evals.run_smoke_eval`
- Extensibility: `cellin.runtime.PluginRegistry` and the contracts exported from `cellin.core`
