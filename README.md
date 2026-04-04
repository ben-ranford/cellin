# cellin

Cellin is a pluggable multimodal memory system for large knowledge graphs. It ingests
artifacts into a long-lived memory substrate, retrieves context with weighted ranking, and
runs "dream" passes that consolidate and simplify memory over time.

## Status

The repository is in active bootstrap. The current goal is to land the local-first MVP:

- Python workspace and repo rigor foundations
- typed memory and plugin contracts
- multimodal ingestion with local stores
- weighted retrieval and memory bundles
- dream scheduling and graph consolidation
- eval harnesses and starter workflows

## Quickstart

1. Install Python `3.12`.
2. Install `uv`.
3. Run `make bootstrap`.
4. Run `make ci`.

## Developer Commands

- `make bootstrap`
- `make fmt`
- `make lint`
- `make typecheck`
- `make test`
- `make eval-smoke`
- `make verify`
- `make ci`

## Documentation

- [Architecture Overview](docs/architecture/README.md)
- [Eval Strategy](docs/evals/README.md)
- [Implementation Plan](docs/pluggable-evals-rigor-plan.md)
