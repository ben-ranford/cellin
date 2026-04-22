"""Protocol contracts for Cellin plugins and runtime components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from cellin.core.models import (
    Artifact,
    DreamArtifact,
    EmbeddingRecord,
    Entity,
    EvaluationResult,
    JSONValue,
    MemoryAtom,
    MemoryBundle,
    MemoryEdge,
    Modality,
    ScheduledDreamRun,
    ScoredMemory,
    TraceEvent,
    VectorMatch,
)


class Capability(StrEnum):
    """Runtime capabilities supported by a plugin."""

    CHUNKER = "chunker"
    CONSOLIDATOR = "consolidator"
    CROSS_MODAL_ALIGNER = "cross_modal_aligner"
    DREAM_SCHEDULER = "dream_scheduler"
    DREAM_STRATEGY = "dream_strategy"
    ENTITY_EXTRACTOR = "entity_extractor"
    EVALUATOR = "evaluator"
    GRAPH_STORE = "graph_store"
    INGESTOR = "ingestor"
    MEMORY_STORE = "memory_store"
    MODALITY_ADAPTER = "modality_adapter"
    RANKER = "ranker"
    REPRESENTATION_PROVIDER = "representation_provider"
    RETRIEVER = "retriever"
    TRACE_SINK = "trace_sink"


@dataclass(slots=True)
class PluginManifest:
    """Describes a plugin and the capabilities it exposes."""

    plugin_id: str
    version: str
    capabilities: tuple[Capability, ...]
    display_name: str | None = None
    description: str | None = None
    entrypoint: str | None = None
    config_schema: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeConfig:
    """Top-level runtime config shared across plugins."""

    plugins: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    default_modality: Modality = Modality.TEXT


@dataclass(slots=True)
class PluginContext:
    """Context passed to a plugin during runtime configuration."""

    runtime_id: str
    config: RuntimeConfig
    plugin_settings: Mapping[str, JSONValue] = field(default_factory=dict)


class Plugin(Protocol):
    """Lifecycle hooks required for every Cellin plugin."""

    manifest: PluginManifest

    def configure(self, context: PluginContext) -> None:
        """Configure the plugin with runtime state."""

    def start(self) -> None:
        """Start the plugin after configuration."""

    def stop(self) -> None:
        """Stop the plugin and release resources."""


class GraphStore(Protocol):
    """Graph persistence operations used by retrieval and dreaming."""

    def upsert_memory(self, memory: MemoryAtom) -> None:
        """Persist or update a graph node."""

    def upsert_edge(self, edge: MemoryEdge) -> None:
        """Persist or update a graph edge."""

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        """Return a single graph node."""

    def neighbors(self, memory_id: str) -> Sequence[MemoryEdge]:
        """Return adjacent graph edges."""

    def list_edges(self) -> Sequence[MemoryEdge]:
        """Return all active graph edges."""

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        """Return True if this graph store and memory_store write to the same backend."""
        return False


class MemoryStore(Protocol):
    """Persistence operations for retrievable memory atoms."""

    def put(self, memory: MemoryAtom) -> None:
        """Store a memory atom."""

    def get(self, memory_id: str) -> MemoryAtom | None:
        """Fetch a stored memory atom."""

    def list(self) -> Sequence[MemoryAtom]:
        """List all stored memories."""

    def list_by(
        self,
        *,
        archived: bool | None = None,
        topic: str | None = None,
    ) -> Sequence[MemoryAtom]:
        """Return memories filtered by archived state and/or topic."""
        ...


class Ingestor(Protocol):
    """Transforms artifacts into memory atoms and graph edges."""

    def ingest(self, artifacts: Sequence[Artifact]) -> Sequence[MemoryAtom]:
        """Ingest a sequence of artifacts."""


class ModalityAdapter(Protocol):
    """Normalizes raw modality-specific input into an artifact."""

    def supports(self, modality: Modality) -> bool:
        """Whether the adapter supports a given modality."""

    def normalize(self, payload: object) -> Artifact:
        """Normalize a raw payload into a first-class artifact."""


class Chunker(Protocol):
    """Breaks artifacts into smaller memory-ready chunks."""

    def chunk(self, artifact: Artifact) -> Sequence[str]:
        """Chunk an artifact into smaller spans."""


class EntityExtractor(Protocol):
    """Extracts entities from an artifact."""

    def extract(self, artifact: Artifact) -> Sequence[Entity]:
        """Extract entities from an artifact."""


class CrossModalAligner(Protocol):
    """Creates links between related artifacts across modalities."""

    def align(self, artifacts: Sequence[Artifact]) -> Sequence[MemoryEdge]:
        """Produce cross-modal memory edges."""


class DreamStrategy(Protocol):
    """Optimizes existing memory state through a controlled dream pass."""

    def run(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        at: datetime | None = None,
    ) -> Sequence[DreamArtifact]:
        """Run the dream strategy against the current memory state."""


class DreamScheduler(Protocol):
    """Plans future dream runs."""

    def plan(self, now: datetime) -> Sequence[ScheduledDreamRun]:
        """Return scheduled dream runs."""


class Consolidator(Protocol):
    """Creates more useful memory state from related memory atoms."""

    def consolidate(self, memories: Sequence[MemoryAtom]) -> Sequence[DreamArtifact]:
        """Consolidate a group of related memories."""


class Retriever(Protocol):
    """Builds memory bundles for downstream use."""

    def retrieve(self, query: str, top_k: int = 5) -> MemoryBundle:
        """Retrieve a scored memory bundle."""


class Ranker(Protocol):
    """Scores candidate memory atoms for retrieval."""

    def score(self, query: str, memories: Sequence[MemoryAtom]) -> Sequence[ScoredMemory]:
        """Score candidate memories for a query."""


class RepresentationProvider(Protocol):
    """Provides embeddings or other retrieval representations."""

    def embed(self, inputs: Sequence[str]) -> Sequence[EmbeddingRecord]:
        """Create retrieval representations for text inputs."""


class Evaluator(Protocol):
    """Runs a specific evaluation or benchmark suite."""

    def run(self, evaluation_id: str) -> EvaluationResult:
        """Run a named evaluation."""


class TraceSink(Protocol):
    """Consumes structured trace events."""

    def record(self, event: TraceEvent) -> None:
        """Record a trace event."""


class VectorStore(Protocol):
    """Vector indexing primitives for memory and representation retrieval."""

    def upsert(self, memory_id: str, text: str) -> None:
        """Add or update an indexed vector for a memory id."""

    def search(self, query: str, *, limit: int = 5) -> Sequence[VectorMatch]:
        """Return matching memory ids and scores."""

    def delete(self, memory_id: str) -> None:
        """Remove an indexed vector for a memory id."""
        ...
