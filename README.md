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


## Primary surfaces

- CLI: `cellin init`, `ingest`, `retrieve`, `dream`, `plugin list`, `eval run`, `trace inspect`
- Ingestion: `cellin.ingest.ArtifactEnvelope` and `cellin.ingest.CanonicalIngestor`
- Retrieval: `cellin.retrieval.WeightedRetriever`, `cellin.retrieval.RetrievalCandidateGenerator`, and `cellin.ranking.WeightedRanker`
- Dreaming: `cellin.dreaming.DreamRunner` plus the built-in deduplication, abstraction, and contradiction-repair strategies
- Evals: `cellin.evals.run_evaluation_suite` and `cellin.evals.run_smoke_eval`
- Extensibility: `cellin.runtime.PluginRegistry` and the contracts exported from `cellin.core`
