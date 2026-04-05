# cellin

Cellin is a pluggable multimodal memory system for large knowledge graphs. It ingests
artifacts into a long-lived memory substrate, retrieves context with weighted ranking, and
runs "dream" passes that consolidate and simplify memory over time.

Cellin can be used as a Python library or through the local CLI.

## Quickstart

1. Install Python `3.12`.
2. Install `uv`.
3. Run `make bootstrap`.
4. Run `python3 -m uv run cellin ingest --config examples/starter/cellin-starter.json --input examples/starter/seed_envelopes.json`.
5. Run `python3 -m uv run cellin retrieve --config examples/starter/cellin-starter.json --query "memory graph retrieval" --top-k 2`.
6. Run `python3 -m uv run cellin dream --config examples/starter/cellin-starter.json --strategy abstraction`.
7. Run `python3 -m uv run cellin eval run --suite smoke --config examples/starter/cellin-starter.json --output eval-results/starter-smoke.json`.
8. Run `python3 -m uv run cellin trace inspect --config examples/starter/cellin-starter.json --limit 5`.
