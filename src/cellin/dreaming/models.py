"""Dream execution models and machine-readable diff output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cellin.core import DreamArtifact, MemoryAtom, MemoryEdge
from cellin.core.models import JSONValue


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _memory_snapshot(memory: MemoryAtom | None) -> JSONValue:
    if memory is None:
        return None

    return {
        "memory_id": memory.memory_id,
        "kind": memory.kind.value,
        "text": memory.text,
        "modality": memory.modality.value,
        "artifact_id": memory.artifact_id,
        "created_at": memory.created_at.isoformat(),
        "observed_at": _format_datetime(memory.observed_at),
        "salience_score": memory.salience_score,
        "trust_score": memory.trust_score,
        "archived": memory.decay.archived,
        "access_count": memory.retrieval.access_count,
        "metadata": memory.metadata,
    }


def _edge_snapshot(edge: MemoryEdge | None) -> JSONValue:
    if edge is None:
        return None

    return {
        "edge_id": edge.edge_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "kind": edge.kind.value,
        "created_at": edge.created_at.isoformat(),
        "weight": edge.weight,
        "metadata": edge.metadata,
    }


@dataclass(slots=True)
class DreamMemoryChange:
    """A before/after mutation applied to a memory atom."""

    memory_id: str
    before: MemoryAtom | None
    after: MemoryAtom | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "memory_id": self.memory_id,
            "before": _memory_snapshot(self.before),
            "after": _memory_snapshot(self.after),
        }


@dataclass(slots=True)
class DreamEdgeChange:
    """A before/after mutation applied to a graph edge."""

    edge_id: str
    before: MemoryEdge | None
    after: MemoryEdge | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "edge_id": self.edge_id,
            "before": _edge_snapshot(self.before),
            "after": _edge_snapshot(self.after),
        }


@dataclass(slots=True)
class DreamDiff:
    """A reversible, machine-readable dream mutation log."""

    run_id: str
    strategy_name: str
    created_at: datetime
    memory_changes: tuple[DreamMemoryChange, ...] = ()
    edge_changes: tuple[DreamEdgeChange, ...] = ()
    notes: dict[str, JSONValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "created_at": self.created_at.isoformat(),
            "memory_changes": [change.to_dict() for change in self.memory_changes],
            "edge_changes": [change.to_dict() for change in self.edge_changes],
            "notes": self.notes,
        }


@dataclass(slots=True)
class DreamRunResult:
    """A fully applied dream run and its reversible diff."""

    artifact: DreamArtifact
    diff: DreamDiff
