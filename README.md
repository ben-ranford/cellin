# cellin

Cellin is a pluggable multimodal memory system for large knowledge graphs. It ingests
artifacts into a long-lived memory substrate, retrieves context with weighted ranking, and
runs "dream" passes that consolidate and simplify memory over time.

## MVP Surface

The current local-first MVP already includes:

- typed memory objects and plugin contracts for ingestion, retrieval, dreaming, evaluation,
  and storage
- first-party adapters for `text`, `markdown`, `chat`, `json`, and `image` envelopes
- local persistence through SQLite-backed graph and memory stores plus an in-memory vector
  index for retrieval candidates
- weighted retrieval with explainable factor scoring across semantic similarity, graph
  proximity, recency, salience, trust, reinforcement, and modality match
- dream passes for `deduplication`, `contradiction_repair`, and `abstraction`
- a thin local CLI for `init`, `ingest`, `retrieve`, `dream`, `plugin list`, `eval run`,
  and `trace inspect`
- deterministic eval suites, a runnable starter example, and release-grade repo rigor

## Quickstart

1. Install Python `3.12`.
2. Install `uv`.
3. Run `make bootstrap`.
4. Run `make ci`.
5. Run `python3 -m uv run cellin plugin list`.

## Install

Stable release from PyPI:

```bash
pip install cellin
```

Prerelease from PyPI:

```bash
pip install --pre cellin
```

## Library Surface

Cellin can be used as a Python library as well as a CLI:

```python
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore
```

The stable import surfaces today are the subpackages under `cellin.core`, `cellin.ingest`,
`cellin.retrieval`, `cellin.ranking`, `cellin.dreaming`, `cellin.evals`, `cellin.runtime`,
and `cellin.stores`.

## Starter Workflow

Run the local MVP loop from the repository root:

1. `python3 -m uv run cellin ingest --config examples/starter/cellin-starter.json --input examples/starter/seed_envelopes.json`
2. `python3 -m uv run cellin retrieve --config examples/starter/cellin-starter.json --query "memory graph retrieval" --top-k 2`
3. `python3 -m uv run cellin dream --config examples/starter/cellin-starter.json --strategy abstraction`
4. `python3 -m uv run cellin eval run --suite smoke --config examples/starter/cellin-starter.json --output eval-results/starter-smoke.json`
5. `python3 -m uv run cellin trace inspect --config examples/starter/cellin-starter.json --limit 5`

If you want a fresh workspace instead of the seeded starter config:

1. `python3 -m uv run cellin init --workspace ./.cellin-local`
2. Edit `./.cellin-local/cellin.json` if you want a non-default database path, trace path, or retrieval profile.
3. Point the same `ingest`, `retrieve`, `dream`, `eval run`, and `trace inspect` commands at that config.

## MVP Landing Checklist

Treat the MVP as shippable only if these stay green:

- `make ci`
- `make eval-full`
- `make package-smoke`
- `make release-smoke`
- the starter workflow in [examples/starter/README.md](examples/starter/README.md)

## CLI Surface

- `python3 -m uv run cellin init --workspace <dir-or-config>`
  Creates a workspace config with local SQLite and trace paths.
- `python3 -m uv run cellin ingest --config <path> --input <json>`
  Normalizes envelopes and writes artifacts, memories, and graph edges.
- `python3 -m uv run cellin retrieve --config <path> --query <text> --top-k <n>`
  Returns a scored memory bundle with explainable factor output.
- `python3 -m uv run cellin dream --config <path> [--strategy abstraction|deduplication|contradiction_repair]`
  Runs one dream strategy or any pending scheduled strategies.
- `python3 -m uv run cellin plugin list`
  Lists built-in and entry-point plugins discoverable by the runtime.
- `python3 -m uv run cellin eval run --suite smoke|full [--config <path>] [--output <json>]`
  Runs deterministic eval suites and writes machine-readable reports.
- `python3 -m uv run cellin trace inspect --config <path> --limit <n>`
  Reads recent structured trace events emitted by the CLI workflow.

## Developer Commands

- `make bootstrap`
- `make fmt`
- `make lint`
- `make typecheck`
- `make test`
- `make eval-smoke`
- `make eval-full`
- `make eval`
- `make docs`
- `make package`
- `make package-smoke`
- `make release-smoke`
- `make verify`
- `make ci`

## Documentation

- [Architecture Overview](docs/architecture/README.md)
- [Eval Strategy](docs/evals/README.md)
- [Starter Example](examples/starter/README.md)
- [Release Guide](RELEASING.md)
- [Implementation Plan](docs/pluggable-evals-rigor-plan.md)

## Release Channels

- Stable releases are published from pushed semver tags such as `v0.1.0` through `.github/workflows/release.yml`.
- Prereleases are published from manual GitHub Actions runs through `.github/workflows/rolling-release.yml`.
- Python package versions follow semver-compatible PEP 440 syntax: stable `X.Y.Z`, prerelease `X.Y.ZrcN`, `X.Y.ZbN`, or `X.Y.ZaN`.
