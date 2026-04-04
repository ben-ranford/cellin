"""Shared domain models for Cellin's memory system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

type JSONValue = str | int | float | bool | None | dict[str, "JSONValue"] | list["JSONValue"]


class Modality(StrEnum):
    """First-class modalities that Cellin can reason about."""

    TEXT = "text"
    CHAT = "chat"
    MARKDOWN = "markdown"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class MemoryKind(StrEnum):
    """The kinds of memory objects the system currently models."""

    ARTIFACT = "artifact"
    EPISODE = "episode"
    ENTITY = "entity"
    CONCEPT = "concept"
    ATOM = "atom"
    DREAM = "dream"


class EdgeKind(StrEnum):
    """Typed relationships between memory objects."""

    ABOUT = "about"
    CAUSED_BY = "caused_by"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"
    SAME_AS = "same_as"
    SUMMARIZES = "summarizes"
    SUPPORTS = "supports"


@dataclass(slots=True)
class Provenance:
    """Source-of-truth metadata for any memory object."""

    source_id: str
    source_type: str
    uri: str | None = None
    ingest_run_id: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class DecayState:
    """Decay metadata used by retrieval and dream policies."""

    archived: bool = False
    half_life_days: float | None = None
    last_reinforced_at: datetime | None = None


@dataclass(slots=True)
class RetrievalStats:
    """Basic retrieval counters kept on retrievable memory objects."""

    access_count: int = 0
    last_accessed_at: datetime | None = None


@dataclass(slots=True)
class EmbeddingRecord:
    """Reference data for an embedding attached to a memory object."""

    key: str
    vector: tuple[float, ...]
    model: str | None = None


@dataclass(slots=True)
class Artifact:
    """A source artifact that entered the memory system."""

    artifact_id: str
    modality: Modality
    content: str
    provenance: Provenance
    created_at: datetime
    observed_at: datetime | None = None
    trust_score: float = 1.0
    salience_score: float = 0.5
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class Episode:
    """A time-bound interaction or observation."""

    episode_id: str
    title: str
    provenance: Provenance
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None
    participants: tuple[str, ...] = ()
    trust_score: float = 1.0
    salience_score: float = 0.5
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class Entity:
    """A stable named thing in the memory graph."""

    entity_id: str
    label: str
    entity_type: str
    provenance: Provenance
    aliases: tuple[str, ...] = ()
    salience_score: float = 0.5
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class Concept:
    """A stable abstraction inferred across episodes or artifacts."""

    concept_id: str
    name: str
    provenance: Provenance
    summary: str | None = None
    related_entity_ids: tuple[str, ...] = ()
    salience_score: float = 0.5
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryAtom:
    """The smallest retrievable memory unit with provenance."""

    memory_id: str
    kind: MemoryKind
    text: str
    provenance: Provenance
    modality: Modality
    created_at: datetime
    observed_at: datetime | None = None
    artifact_id: str | None = None
    salience_score: float = 0.5
    trust_score: float = 1.0
    decay: DecayState = field(default_factory=DecayState)
    retrieval: RetrievalStats = field(default_factory=RetrievalStats)
    embeddings: tuple[EmbeddingRecord, ...] = ()
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryEdge:
    """A typed edge between two memory objects."""

    edge_id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    provenance: Provenance
    created_at: datetime
    weight: float = 1.0
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class DreamArtifact:
    """A synthetic artifact produced by a dream or consolidation pass."""

    dream_id: str
    strategy_name: str
    provenance: Provenance
    created_at: datetime
    summary: str
    affected_memory_ids: tuple[str, ...]
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class FactorScore:
    """A single explainable contribution to a memory score."""

    name: str
    value: float
    rationale: str | None = None


@dataclass(slots=True)
class ScoredMemory:
    """A retrievable memory with a composed score."""

    memory: MemoryAtom
    score: float
    factors: tuple[FactorScore, ...] = ()


@dataclass(slots=True)
class MemoryBundle:
    """A compact retrieval bundle returned to downstream consumers."""

    query: str
    memories: tuple[ScoredMemory, ...]
    total_score: float
    summary: str | None = None
    token_budget: int | None = None


@dataclass(slots=True)
class TraceEvent:
    """Structured runtime trace data."""

    name: str
    timestamp: datetime
    payload: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationResult:
    """A single evaluation or benchmark outcome."""

    evaluation_id: str
    status: str
    metrics: dict[str, float] = field(default_factory=dict)
    notes: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduledDreamRun:
    """A dream run that has been planned but not executed."""

    strategy_name: str
    scheduled_for: datetime
    reason: str
