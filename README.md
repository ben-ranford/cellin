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

## Quickstart

From the repository root:

```bash
WORKSPACE=.cellin-workspace
python3 -m uv run cellin init --workspace "$WORKSPACE"
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
  "memory": { "backend": "postgresql", "database_path": "postgresql://user:pass@host:5432/db" },
  "graph": { "backend": "postgresql", "database_path": "postgresql://user:pass@host:5432/db" }
}

{
  "memory": { "backend": "mysql", "database_path": "mysql://user:pass@host:3306/db" },
  "graph": { "backend": "mysql", "database_path": "mysql://user:pass@host:3306/db" }
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
  "memory": { "backend": "mongodb", "database_path": "mongodb://user:pass@host:27017/cellin" },
  "graph": { "backend": "mongodb", "database_path": "mongodb://user:pass@host:27017/cellin" }
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
  "graph": { "backend": "neo4j", "database_path": "bolt://user:pass@host:7687" }
}
```

Graph-native stores persist edge relationships plus graph-local memory payload snapshots. When
`GraphStore.get_memory()` is asked for a node that only exists as a placeholder created during edge
upserts, it returns `None` and retrieval falls back to the configured memory store as the source of
truth. That keeps mixed deployments working without caller changes while making the graph-local
snapshot behavior explicit.


## Primary surfaces

- CLI: `cellin init`, `ingest`, `retrieve`, `dream`, `plugin list`, `eval run`, `trace inspect`
- Ingestion: `cellin.ingest.ArtifactEnvelope` and `cellin.ingest.CanonicalIngestor`
- Retrieval: `cellin.retrieval.WeightedRetriever`, `cellin.retrieval.RetrievalCandidateGenerator`, and `cellin.ranking.WeightedRanker`
- Dreaming: `cellin.dreaming.DreamRunner` plus the built-in deduplication, abstraction, and contradiction-repair strategies
- Evals: `cellin.evals.run_evaluation_suite` and `cellin.evals.run_smoke_eval`
- Extensibility: `cellin.runtime.PluginRegistry` and the contracts exported from `cellin.core`
