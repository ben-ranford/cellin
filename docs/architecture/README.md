# Architecture

Cellin is being built around these boundaries:

- `cellin.core`: domain objects and plugin contracts
- `cellin.runtime`: plugin loading and orchestration
- `cellin.ingest`: multimodal normalization and memory writes
- `cellin.retrieval` and `cellin.ranking`: weighted evidence aggregation
- `cellin.dreaming`: consolidation and graph rewrites
- `cellin.evals`: deterministic and benchmarked quality checks

The system is intended to stay local-first and pluggable at every boundary where modality,
storage, ranking, or dream policy may vary.

The `cellin.cli` layer is intentionally thin. It creates a workspace config, then calls the
same `cellin.ingest`, `cellin.retrieval`, `cellin.dreaming`, and `cellin.evals` modules that
the integration tests and eval harness already exercise. This keeps the starter workflow
representative of the actual runtime rather than introducing a second orchestration path.
