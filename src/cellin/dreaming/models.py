"""Dream execution models and machine-readable diff output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from cellin.core import DreamArtifact, MemoryAtom, MemoryEdge
from cellin.core.models import (
    DecayState,
    EdgeKind,
    JSONValue,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime:
    assert isinstance(value, str)
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    assert isinstance(value, str)
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _memory_from_snapshot(raw: object) -> MemoryAtom | None:
    if raw is None:
        return None
    assert isinstance(raw, dict)
    return MemoryAtom(
        memory_id=str(raw["memory_id"]),
        kind=MemoryKind(str(raw["kind"])),
        text=str(raw["text"]),
        provenance=Provenance(source_id="dream-diff", source_type="rollback"),
        modality=Modality(str(raw["modality"])),
        created_at=_parse_datetime(raw["created_at"]),
        observed_at=_parse_optional_datetime(raw.get("observed_at")),
        artifact_id=str(raw["artifact_id"]) if raw.get("artifact_id") is not None else None,
        salience_score=float(raw.get("salience_score", 0.5)),
        trust_score=float(raw.get("trust_score", 1.0)),
        decay=DecayState(archived=bool(raw.get("archived", False))),
        retrieval=RetrievalStats(access_count=int(raw.get("access_count", 0))),
        metadata=dict(raw.get("metadata", {})),
    )


def _edge_from_snapshot(raw: object) -> MemoryEdge | None:
    if raw is None:
        return None
    assert isinstance(raw, dict)
    return MemoryEdge(
        edge_id=str(raw["edge_id"]),
        source_id=str(raw["source_id"]),
        target_id=str(raw["target_id"]),
        kind=EdgeKind(str(raw["kind"])),
        provenance=Provenance(source_id="dream-diff", source_type="rollback"),
        created_at=_parse_datetime(raw["created_at"]),
        weight=float(raw.get("weight", 1.0)),
        metadata=dict(raw.get("metadata", {})),
    )


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

    @classmethod
    def from_dict(cls, d: dict[str, JSONValue]) -> DreamMemoryChange:
        return cls(
            memory_id=str(d["memory_id"]),
            before=_memory_from_snapshot(d.get("before")),
            after=_memory_from_snapshot(d.get("after")),
        )


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

    @classmethod
    def from_dict(cls, d: dict[str, JSONValue]) -> DreamEdgeChange:
        return cls(
            edge_id=str(d["edge_id"]),
            before=_edge_from_snapshot(d.get("before")),
            after=_edge_from_snapshot(d.get("after")),
        )


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

    @classmethod
    def from_dict(cls, d: dict[str, JSONValue]) -> DreamDiff:
        assert isinstance(d["memory_changes"], list)
        assert isinstance(d["edge_changes"], list)
        return cls(
            run_id=str(d["run_id"]),
            strategy_name=str(d["strategy_name"]),
            created_at=_parse_datetime(d["created_at"]),
            memory_changes=tuple(
                DreamMemoryChange.from_dict(c)  # type: ignore[arg-type]
                for c in d["memory_changes"]
            ),
            edge_changes=tuple(
                DreamEdgeChange.from_dict(c)  # type: ignore[arg-type]
                for c in d["edge_changes"]
            ),
            notes=dict(d.get("notes", {})),  # type: ignore[arg-type]
        )


@dataclass(slots=True)
class DreamRunResult:
    """A fully applied dream run and its reversible diff."""

    artifact: DreamArtifact
    diff: DreamDiff
