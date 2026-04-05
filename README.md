# cellin

[![PyPI](https://img.shields.io/pypi/v/cellin)](https://pypi.org/project/cellin/)
[![Release](https://img.shields.io/github/v/release/ben-ranford/cellin)](https://github.com/ben-ranford/cellin/releases)

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

## Primary surfaces

- CLI: `cellin init`, `ingest`, `retrieve`, `dream`, `plugin list`, `eval run`, `trace inspect`
- Ingestion: `cellin.ingest.ArtifactEnvelope` and `cellin.ingest.CanonicalIngestor`
- Retrieval: `cellin.retrieval.WeightedRetriever`, `cellin.retrieval.RetrievalCandidateGenerator`, and `cellin.ranking.WeightedRanker`
- Dreaming: `cellin.dreaming.DreamRunner` plus the built-in deduplication, abstraction, and contradiction-repair strategies
- Evals: `cellin.evals.run_evaluation_suite` and `cellin.evals.run_smoke_eval`
- Extensibility: `cellin.runtime.PluginRegistry` and the contracts exported from `cellin.core`
