"""Envelope models for artifact ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cellin.core import Artifact, MemoryAtom, MemoryEdge, Modality
from cellin.core.models import JSONValue


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    """A canonical ingest envelope before modality-specific normalization."""

    envelope_id: str
    modality: Modality
    payload: str | dict[str, JSONValue] | list[JSONValue]
    source_id: str
    source_type: str
    observed_at: datetime
    metadata: dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class IngestionBatchResult:
    """Artifacts, memories, and edges produced by a single ingest batch."""

    artifacts: tuple[Artifact, ...]
    memories: tuple[MemoryAtom, ...]
    edges: tuple[MemoryEdge, ...]
