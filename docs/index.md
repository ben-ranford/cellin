# Cellin

Cellin is a pluggable multimodal memory system that ingests artifacts into a long-lived
memory graph, retrieves memory bundles with transparent weighting, and runs dream passes to
consolidate or simplify that graph over time.

## Current priorities

- repository rigor and contributor workflow
- typed core contracts and runtime boundaries
- local-first multimodal ingestion
- weighted retrieval and explainable bundles
- dream-driven consolidation
- evals that measure pre- and post-dream quality

## Local workflow

The CLI exercises the same ingest, retrieval, dreaming, and eval paths that the tests use.

1. `python -m cellin.cli init --workspace ./.cellin`
2. `python -m cellin.cli ingest --config examples/starter/cellin-starter.json --input examples/starter/seed_envelopes.json`
3. `python -m cellin.cli retrieve --config examples/starter/cellin-starter.json --query "memory graph retrieval" --top-k 2`
4. `python -m cellin.cli dream --config examples/starter/cellin-starter.json --strategy abstraction`
5. `python -m cellin.cli eval run --suite smoke --config examples/starter/cellin-starter.json --output eval-results/starter-smoke.json`
6. `python -m cellin.cli trace inspect --config examples/starter/cellin-starter.json --limit 5`
