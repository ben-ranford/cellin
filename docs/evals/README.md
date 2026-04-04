# Evals

Cellin evals are version-controlled product assets, not notebooks or one-off experiments.

## Suites

- `make eval-smoke`
  Runs the deterministic PR gate and writes `eval-results/smoke.json`.
- `make eval-full`
  Runs the broader benchmark suite and writes `eval-results/full.json`.

## Seeded corpora

The repository tracks deterministic corpora under `evals/corpora/` for:

- conversational memory and duplicate-note pressure
- project memory and graph-linked retrieval
- multimodal artifact ingestion
- contradiction repair
- recency traps

## Reporting

Every report includes:

- per-case metrics
- baseline metrics
- delta metrics for before/after comparisons
- machine-readable notes such as dream diffs and expected ids

PR CI runs the smoke suite. Scheduled and manually dispatched workflow runs execute the full
suite and upload the resulting JSON artifact.
