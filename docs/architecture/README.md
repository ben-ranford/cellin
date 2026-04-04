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
