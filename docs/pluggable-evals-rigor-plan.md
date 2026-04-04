# Cellin Plan: Pluggable Multimodal Memory, Dreaming, Evals, and Repo Rigor

## Purpose

Define a practical starting plan for turning `cellin` into a pluggable, batteries-included multimodal memory system that ingests data into a long-lived knowledge graph, retrieves it with weighted ranking, and "dreams" to consolidate, simplify, and improve future recall. Evals are built into the development loop, and repository rigor is aligned to `repo-rigor-uplift`.

## Direct Evidence From The Repository

### Tracked Repository State

- The tracked repository currently contains only `README.md`.
- The README scope is one sentence: "Memory & dreaming mechanism for large knowledge graphs."
- There is no implementation, package manifest, task runner, hook manager, CI workflow, release automation, or governance files in the tracked repository.

### Remote GitHub Surface

- The repo has default GitHub labels only.
- No rulesets are configured.
- No milestones are configured.
- No GitHub Actions workflows are configured.
- There is an open Renovate onboarding branch/PR (`renovate/configure`) that adds a minimal `renovate.json`, but it is not merged into `main`.

### Audit Summary

Audit results for the current repository state:

- Current overall tier: `baseline`
- `local-gates`: `0/4`
- `ci-gates`: `0/4`
- `release`: `0/4`
- `governance`: `3/4`

## Planning Assumptions

These are recommendations, not existing repo facts.

1. `cellin` should be Python-first.
   Reason: the domain needs LLM, multimodal processing, retrieval, graph, and eval tooling quickly; Python is the lowest-friction ecosystem for that combination.
2. The repo should target `strict` rigor immediately.
   Reason: pluggability, weighted retrieval, and dream-based consolidation create regression risk at integration boundaries early.
3. The repo should be designed so it can reach `release-grade` without a structural rewrite.
   Reason: if `cellin` becomes a package, service, or plugin ecosystem, release automation and compatibility policy will matter quickly.

## Product Scope

The intended product is an LLM memory engine with four core responsibilities:

1. ingest multimodal inputs into a unified memory substrate
2. organize those memories into a graph of episodes, concepts, entities, artifacts, and derived abstractions
3. retrieve the right memory bundle using weighted ranking that accounts for more than vector similarity
4. run dream cycles that consolidate, deduplicate, abstract, relink, and prune the graph to improve future retrieval quality

The initial implementation should support:

- text, markdown, JSON, and conversational messages as first-class inputs
- image inputs with captions or OCR-derived text as the first multimodal extension
- optional audio and video via transcription adapters later
- both direct recall and synthesized memory bundle retrieval
- scheduled and event-driven dream passes

## Product Principles

- memory is not just stored context; it is a changing system asset
- retrieval quality matters more than raw memory volume
- dream passes should pay for themselves by improving later recall, reducing noise, or compressing state
- multimodal content should share common memory primitives, not separate siloed stores
- the default local system should work without external infrastructure beyond an LLM provider
- every dream action should be inspectable, attributable, and reversible

## Target System Shape

Build `cellin` as a small monorepo centered on stable interfaces, a built-in plugin runtime, a first-party eval harness, and an end-to-end memory pipeline that goes from ingestion to retrieval to dream-driven consolidation.

Recommended top-level layout:

```text
cellin/
  README.md
  pyproject.toml
  Makefile
  lefthook.yml
  .github/
    workflows/
    PULL_REQUEST_TEMPLATE.md
    ISSUE_TEMPLATE/
  .config/
    cellin.example.toml
  docs/
    architecture/
    evals/
    operations/
  packages/
    cellin-core/
    cellin-ingest/
    cellin-runtime/
    cellin-ranking/
    cellin-dreaming/
    cellin-cli/
    cellin-evals/
    cellin-builtins/
    cellin-observability/
    cellin-plugin-sdk/
  plugins/
    modality-adapters/
    graph-memory/
    dream-strategies/
    stores/
    rankers/
    model-providers/
  examples/
    local-starter/
    graph-rag/
    multimodal-memory/
  tests/
    unit/
    integration/
    contracts/
  evals/
    cases/
    fixtures/
    golden/
    benchmarks/
```

## Architecture Plan

### 1. Define Stable Core Interfaces First

Keep the core package narrow and mostly abstract. It should define:

- `MemoryAtom`
- `MemoryEdge`
- `MemoryBundle`
- `Episode`
- `Concept`
- `Entity`
- `Artifact`
- `DreamArtifact`
- `GraphStore`
- `MemoryStore`
- `Ingestor`
- `ModalityAdapter`
- `Chunker`
- `EntityExtractor`
- `CrossModalAligner`
- `DreamStrategy`
- `DreamScheduler`
- `Consolidator`
- `Retriever`
- `Ranker`
- `Embedder` or `RepresentationProvider`
- `Planner` or `Scheduler`
- `Evaluator`
- `TraceSink`
- `Plugin` and `PluginManifest`

Rules:

- Core owns contracts, config schemas, lifecycle hooks, and shared result models.
- Core does not depend on vendor SDKs, databases, or specific model providers.
- Built-in and third-party plugins implement the interfaces.

### 2. Establish A Memory-Centric Domain Model

The system should store several distinct memory forms rather than flattening everything into chunks.

Recommended primitives:

- `Episode`: a time-bound observation or interaction
- `Artifact`: a source object such as a message, image, transcript, note, or file
- `Concept`: a stable abstraction inferred across episodes
- `Entity`: person, org, project, tool, place, topic, or user-defined category
- `MemoryAtom`: the smallest retrievable memory unit with provenance
- `MemoryEdge`: typed relation such as `supports`, `contradicts`, `caused_by`, `about`, `derived_from`, `same_as`, `summarizes`
- `DreamArtifact`: a synthetic result of consolidation, abstraction, clustering, contradiction repair, or compression

Every memory object should carry:

- provenance
- modality
- timestamps
- source trust or reliability
- salience or importance score
- decay metadata
- embedding references
- retrieval counters
- dream history

### 3. Build A Multimodal Ingestion Pipeline

The ingestion path should be explicit and inspectable:

1. receive raw input
2. normalize it into a canonical artifact envelope
3. route through modality adapters
4. extract structured signals
5. create memory atoms and edges
6. write graph, vector, and metadata state
7. emit traces and eval events

Recommended first-party modality support:

- text and chat messages
- markdown and plain documents
- JSON records or tool outputs
- images via OCR plus captioning

Later extensions:

- audio via transcription
- video via frame and transcript extraction
- web pages via DOM-to-document normalization
- structured tool traces and agent state snapshots

### 4. Create A Runtime That Composes Plugins Declaratively

The runtime package should:

- load plugins from Python entry points and local config
- validate plugin manifests
- resolve dependency graphs between plugins
- manage startup and shutdown hooks
- expose a registry of active capabilities
- emit structured traces and events for debugging and evals

Use configuration-first composition so a user can stand up a working system with a single config file.

### 5. Design Retrieval As Weighted Evidence Aggregation

Retrieval should start with a transparent scoring pipeline, not a monolithic black-box ranker.

Recommended initial scoring factors:

- semantic similarity
- graph proximity to query-linked entities
- recency with configurable decay
- retrieval reinforcement frequency
- user or task affinity
- modality match between query and candidate memory
- source trust or reliability
- memory salience or importance
- consolidation confidence
- contradiction risk
- compression value
- token or latency cost to include the memory in context

Use a staged ranker:

1. candidate generation from vector and graph search
2. heuristic weighted scoring
3. optional learned or LLM-assisted reranking
4. bundle construction for final context delivery

The weighting system should be configurable per use case. Retrieval for "what happened yesterday?" should weight recency differently from retrieval for "what do we know about this project?".

### 6. Plan Dreaming As Background Optimization

Dreaming should not be treated as free-form creative generation. It is a controlled background optimization pass over memory state.

Recommended dream pass types:

- deduplication dreams
- clustering and abstraction dreams
- contradiction detection and repair dreams
- stale memory compression dreams
- cross-modal linking dreams
- forgotten-but-important resurfacing dreams
- retrieval-failure repair dreams

Recommended dream triggers:

- scheduled cadence
- retrieval misses
- graph growth thresholds
- repeated co-retrieval patterns
- high duplication density
- low-confidence retrieval on important topics

Dream outputs may:

- create abstractions
- merge duplicate or near-duplicate nodes
- add missing edges
- rewrite summaries
- raise or lower salience
- mark memories for archival or aggressive decay

Every dream action should be auditable and reversible.

### 7. Ship First-Party Batteries

The system should feel usable on day one without requiring custom integrations. Include built-in plugins for:

- local graph persistence
  Recommendation: start with SQLite or DuckDB-backed metadata plus a graph abstraction layer; keep Neo4j or Memgraph as optional plugins.
- in-memory development mode
- text and document ingestion adapters
- image OCR and caption ingestion adapter
- a default retriever
- a default weighted ranker
- a default memory consolidation strategy
- at least one dream strategy
- local filesystem artifact store
- OpenAI-compatible model provider abstraction
- trace and metrics export
- CLI scaffolding and inspection commands

### 8. Make Plugin Authoring Cheap

The plugin SDK should provide:

- typed base interfaces
- manifest schema
- plugin scaffold command
- contract test helpers
- version compatibility helpers
- local dev example plugin

This is the difference between "supports plugins" and "is actually pluggable."

### 9. Separate Domain Logic From Serving Surfaces

Treat the engine as the product, not the API framework.

- `cellin-core` and `cellin-runtime` should run without HTTP.
- `cellin-cli` should be the first operational surface.
- If an API is needed, add `cellin-server` later on top of the runtime, likely via FastAPI.

## End-To-End System Flow

The default end-to-end product loop should be:

1. ingest raw multimodal input
2. normalize and enrich it into memory atoms plus graph edges
3. compute embeddings and graph indexes
4. answer retrieval requests through weighted candidate generation and reranking
5. assemble a memory bundle for downstream prompting or agent use
6. observe retrieval outcomes, misses, and follow-up actions
7. schedule dream passes that improve graph quality and bundle quality
8. re-score affected memories and update indexes

The first credible demo should show this flow locally:

- ingest a directory containing notes, chats, and images
- retrieve answers for a small set of benchmark queries
- run one dream cycle
- show that at least some benchmark queries retrieve fewer but more relevant memories after the dream cycle

## Evals Plan

Evals should be a first-class package, not an afterthought in `tests/`.

### 1. Define Eval Layers

Use four layers:

1. Contract evals
   Validate that each plugin obeys the core interface contract.
2. Deterministic system evals
   Seeded fixture graphs and expected outcomes for ingestion, memory creation, recall, consolidation, and dreaming flows.
3. Model-backed quality evals
   Judge output quality with either rubric-based scoring or LLM-as-judge for non-deterministic behavior.
4. Performance and regression evals
   Track latency, cost, graph growth, and retrieval quality over time.

### 2. Evaluate The Full Ingest-To-Dream Loop

The eval system should measure:

- ingestion correctness
- graph construction quality
- retrieval quality before dreams
- retrieval quality after dreams
- dream action quality
- cost, latency, and memory growth over time

### 3. Start With Domain Metrics, Not Generic LLM Metrics

Recommended initial metrics:

- ingestion precision and recall for extracted entities, concepts, and links
- memory write precision
- memory recall hit rate
- top-k retrieval precision and nDCG
- graph node and link precision and recall
- consolidation correctness
- duplication reduction rate
- abstraction usefulness
- dream novelty score
- dream usefulness or downstream retrieval gain
- post-dream retrieval delta
- false merge rate
- contradiction repair quality
- latency per pipeline stage
- token and model cost per run

### 4. Define Eval Corpora Early

Create benchmark corpora that reflect the product:

- conversational memory corpus
- project knowledge corpus
- multimodal artifact corpus with images plus text
- contradictory or stale knowledge corpus
- long-horizon recall corpus with recency traps

For each corpus, store:

- source artifacts
- expected entities and edges
- benchmark retrieval queries
- preferred memory bundles
- expected dream actions or acceptable action families

### 5. Make Evals Runnable Locally And In CI

Provide canonical commands:

- `make eval`
- `make eval-smoke`
- `make eval-contracts`
- `make eval-retrieval`
- `make eval-dreams`
- `make eval-bench`

Recommended behavior:

- PRs run fast deterministic evals and plugin contract checks.
- Nightly or manual workflows run slower model-backed and benchmark evals.
- Benchmark deltas are visible and gated only when thresholds are exceeded.

### 6. Treat Eval Assets As Product Assets

Store eval data under version control:

- small seeded graphs
- canonical tasks
- ingestion fixtures
- golden outputs where deterministic
- rubric definitions
- benchmark thresholds

Avoid opaque notebooks as the primary eval system.

### 7. Define Performance Signals That Matter To The System

Novel factors that are materially relevant to system performance and should be tracked:

- retrieval entropy: whether the scorer is indecisive across many mediocre candidates
- memory bloat rate: growth of low-value or duplicate memory over time
- consolidation yield: how often dream passes produce accepted useful changes
- bundle efficiency: answer quality per token included in retrieved context
- graph navigability: how many hops are required to reach relevant evidence
- modality skew: whether one modality dominates retrieval despite lower quality
- stale dominance: whether old high-salience memories suppress fresher corrections
- write-to-value ratio: how much new memory actually improves later recall

## Batteries-Included Developer Experience

The repo should work out of the box for a new contributor with one bootstrap path.

Recommended stack:

- Python `3.12+`
- `uv` for environment and dependency management
- `pytest` for tests and deterministic eval harness integration
- `ruff` for lint and format
- `mypy` or `pyright` for static typing
- `mkdocs-material` for docs
- `lefthook` for local hook management
- `Makefile` as the canonical top-level entrypoint

Recommended CLI surface:

- `cellin init`
- `cellin ingest`
- `cellin run`
- `cellin retrieve`
- `cellin dream`
- `cellin plugin list`
- `cellin plugin scaffold`
- `cellin eval run`
- `cellin eval compare`
- `cellin trace inspect`

## Repo Rigor Target

### Target Tier

Target `strict` immediately, with `release-grade` scaffolding where it is cheap.

Why not `standard`:

- plugin ecosystems fail at boundaries, not just in unit logic
- eval regression needs to be caught early
- this repo is greenfield, so the lowest-friction time to install rigor is now

### Required Repo Surfaces

Add these before substantive feature work:

- `pyproject.toml`
- `Makefile`
- `lefthook.yml`
- `.github/workflows/verify.yml`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `CODEOWNERS`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `docs/architecture/` and `docs/evals/`

### Canonical Commands

The repo should standardize on:

- `make bootstrap`
- `make fmt`
- `make lint`
- `make typecheck`
- `make test`
- `make eval`
- `make verify`
- `make ci`

Recommended mapping:

- `make verify` is the main local quality gate
- `make ci` is the merge gate and mirrors CI behavior

### Hook Strategy

Use `lefthook`.

Reason:

- this repo is likely to become polyglot over time
- `Makefile` is a good center of gravity for both local and CI execution
- hook logic should stay as thin wrappers around canonical commands

Recommended initial hooks:

- pre-commit: `make fmt` and targeted lint checks
- pre-push: `make test` plus fast deterministic eval smoke

### CI Plan

Start with these workflows:

1. `verify.yml`
   Runs on PRs and pushes to `main`.
   Jobs:
   - format, lint, and typecheck
   - tests
   - ingest and retrieval smoke evals
   - plugin contract tests
2. `nightly-evals.yml`
   Runs on schedule and manual dispatch.
   Jobs:
   - full eval suite
   - dream benchmark comparison
   - artifact upload for reports
3. `release.yml`
   Add once packaging exists.
   Jobs:
   - build
   - publish
   - release notes

### Remote GitHub Governance

Once CI exists, configure the default branch with real required checks only.

Recommended labels in addition to defaults:

- `rigor-uplift`
- `plugin`
- `evals`
- `architecture`
- `dreaming`
- `retrieval`
- `release-candidate`
- `performance`

Recommended milestone scheme:

- use semver milestones if packages are published
- otherwise use calendar-based milestones until the first public release plan exists

Recommended ruleset requirements:

- PR required
- 1 approval minimum
- stale review dismissal on push
- review thread resolution required
- code owner review required
- force-push blocked
- deletion blocked
- required status checks from `verify.yml`

## End-To-End Implementation Plan

### Phase 0: Foundation And Guardrails

Goal: install the repo operating model before adding product logic.

Deliverables:

- merge or supersede the Renovate onboarding PR
- bootstrap Python workspace with `uv`
- create `Makefile`, `lefthook`, lint, types, and test config
- add PR template, issue templates, `CODEOWNERS`, `CONTRIBUTING.md`, `SECURITY.md`
- add `verify.yml`

Exit criteria:

- `make ci` works locally
- PRs have a single required verify workflow
- branch protection or ruleset can be configured with real check names

### Phase 1: Core Contracts, Schemas, And Runtime Skeleton

Goal: create the pluggable backbone.

Deliverables:

- `cellin-core` contracts and domain models
- memory object schemas and provenance model
- plugin manifest schema
- runtime loader and registry
- config loading and validation
- structured trace and event model

Exit criteria:

- one built-in plugin can be loaded through the runtime
- plugin contract tests pass

### Phase 2: Multimodal Ingestion And Memory Writing

Goal: turn raw artifacts into retrievable graph memory.

Deliverables:

- canonical artifact envelope format
- text, markdown, chat, and JSON ingestion plugins
- image ingestion with OCR and caption support
- local graph store plugin
- vector index plus metadata store
- memory write pipeline with provenance and salience defaults
- CLI commands for `ingest` and state inspection
- example multimodal dataset

Exit criteria:

- the system can ingest a mixed local dataset and produce graph plus vector state
- ingestion fixtures pass deterministic assertions on nodes, edges, and provenance

### Phase 3: Weighted Retrieval And Memory Bundling

Goal: retrieve the right memory bundle for downstream use.

Deliverables:

- candidate generation from vector and graph search
- default weighted ranker
- configurable weight profiles for recency-sensitive and concept-sensitive retrieval
- bundle assembly logic with token-budget awareness
- CLI commands for `retrieve`
- retrieval traces that explain score composition

Exit criteria:

- benchmark queries return acceptable top-k precision on seeded corpora
- retrieval explanations make score contributions inspectable

### Phase 4: Dreaming, Consolidation, And Graph Optimization

Goal: improve the memory system after writes and retrievals.

Deliverables:

- dream scheduler with scheduled and event-driven triggers
- default dream strategies for deduplication, abstraction, and contradiction repair
- reversible graph rewrite operations
- salience and decay updates driven by dream outcomes
- CLI commands for `dream`
- dream reports with before and after diffs

Exit criteria:

- at least one benchmark corpus shows measurable post-dream retrieval improvement
- dream passes do not exceed false-merge and regression thresholds

### Phase 5: Evals, Observability, And Regression Control

Goal: make system quality measurable end to end.

Deliverables:

- `cellin-evals` package
- fixture graphs and seeded corpora
- ingestion, retrieval, and dream eval suites
- benchmark reporting and trend comparison
- CI eval smoke
- nightly eval workflow
- trace inspection tooling and structured run reports

Exit criteria:

- PR CI fails on contract or deterministic ingest and retrieval regressions
- nightly evals produce comparable artifacts across runs
- dream delta reports are easy to inspect and compare

### Phase 6: External Surfaces And Extension Hardening

Goal: support wider usage and safer external plugins.

Deliverables:

- optional HTTP server surface
- plugin compatibility versioning policy
- extension author guide
- plugin scaffold templates for new modalities, rankers, and dream strategies
- stronger benchmark and performance gates

Exit criteria:

- third-party plugin author can implement against the SDK without editing core packages
- the local starter example and API surface exercise the same engine

### Phase 7: Release-Grade Packaging

Goal: make the repo safely publishable.

Deliverables:

- automated versioning and changelog
- wheel or package publishing
- release workflow
- semver milestone discipline
- ruleset enforcement with required checks

Exit criteria:

- tagged releases are reproducible and validated
- repo reaches `release-grade` for the chosen artifact surface

## Recommended First Implementation Slice

If work starts now, the best first slice is:

1. establish the Python workspace and canonical commands
2. add repo rigor and CI
3. define the memory object model and core plugin contracts
4. implement text-first ingestion plus a local graph and vector store
5. implement a transparent weighted retriever
6. add contract tests, ingestion fixtures, and retrieval smoke evals

That sequence creates a useful spine and gives dreaming something real to optimize.

## MVP Demonstration Target

The first end-to-end milestone should be a local demo that can:

- ingest notes, chats, and images from a directory
- answer a fixed set of benchmark questions with explainable retrieval scores
- run one dream cycle that deduplicates and abstracts memory
- show improved retrieval quality or reduced bundle noise on at least part of the benchmark set

## Risks To Manage Early

- over-coupling plugin implementations to the runtime
- letting model-provider specifics leak into core interfaces
- building evals that require live external services for every PR
- conflating serving or API code with engine logic
- adopting a graph database too early before the abstraction is proven
- creating dreams that are opaque enough that regressions cannot be explained
- over-weighting recency, novelty, or salience without domain benchmarks
- allowing memory growth to outrun retrieval quality improvements

## Definition Of Success

This plan succeeds if `cellin` becomes:

- pluggable by design, not just by convention
- locally runnable with first-party defaults
- capable of ingesting multimodal artifacts into a unified memory graph
- able to retrieve a high-value memory bundle using weighted ranking
- able to improve future retrieval through auditable dream passes
- eval-driven for behavioral regression and post-dream quality improvement
- strict-rigor from the start
- structurally ready for release-grade automation later
