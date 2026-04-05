"""Shared serialization helpers for memory and graph persistence backends."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from cellin.core import (
    DecayState,
    EdgeKind,
    EmbeddingRecord,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.core.models import JSONValue


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("datetime payload values must be ISO-8601 strings")
    return datetime.fromisoformat(value)


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} payload must be a mapping")
    return {str(key): cast(object, nested) for key, nested in value.items()}


def _require_str(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} payload must be a string")
    return value


def _require_number(value: object, *, field_name: str) -> float:
    if not isinstance(value, int | float):
        raise TypeError(f"{field_name} payload must be numeric")
    return float(value)


def _require_list(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} payload must be a list")
    return tuple(value)


def memory_payload(memory: MemoryAtom) -> dict[str, object]:
    return {
        "memory_id": memory.memory_id,
        "kind": memory.kind.value,
        "text": memory.text,
        "provenance": {
            "source_id": memory.provenance.source_id,
            "source_type": memory.provenance.source_type,
            "uri": memory.provenance.uri,
            "ingest_run_id": memory.provenance.ingest_run_id,
            "metadata": memory.provenance.metadata,
        },
        "modality": memory.modality.value,
        "created_at": _dt(memory.created_at),
        "observed_at": _dt(memory.observed_at),
        "artifact_id": memory.artifact_id,
        "salience_score": memory.salience_score,
        "trust_score": memory.trust_score,
        "decay": {
            "archived": memory.decay.archived,
            "half_life_days": memory.decay.half_life_days,
            "last_reinforced_at": _dt(memory.decay.last_reinforced_at),
        },
        "retrieval": {
            "access_count": memory.retrieval.access_count,
            "last_accessed_at": _dt(memory.retrieval.last_accessed_at),
        },
        "embeddings": [
            {"key": embedding.key, "vector": list(embedding.vector), "model": embedding.model}
            for embedding in memory.embeddings
        ],
        "metadata": memory.metadata,
    }


def load_memory_payload(raw: Mapping[str, object]) -> MemoryAtom:
    provenance = _require_mapping(raw.get("provenance"), field_name="provenance")
    decay = _require_mapping(raw.get("decay"), field_name="decay")
    retrieval = _require_mapping(raw.get("retrieval"), field_name="retrieval")
    embeddings = _require_list(raw.get("embeddings", []), field_name="embeddings")
    created_at = _parse_dt(raw.get("created_at"))
    if created_at is None:
        raise TypeError("created_at payload must be present")

    return MemoryAtom(
        memory_id=_require_str(raw.get("memory_id"), field_name="memory_id"),
        kind=MemoryKind(_require_str(raw.get("kind"), field_name="kind")),
        text=_require_str(raw.get("text"), field_name="text"),
        provenance=Provenance(
            source_id=_require_str(provenance.get("source_id"), field_name="provenance.source_id"),
            source_type=_require_str(
                provenance.get("source_type"),
                field_name="provenance.source_type",
            ),
            uri=cast(str | None, provenance.get("uri")),
            ingest_run_id=cast(str | None, provenance.get("ingest_run_id")),
            metadata=cast(dict[str, JSONValue], provenance.get("metadata", {})),
        ),
        modality=Modality(_require_str(raw.get("modality"), field_name="modality")),
        created_at=created_at,
        observed_at=_parse_dt(raw.get("observed_at")),
        artifact_id=cast(str | None, raw.get("artifact_id")),
        salience_score=_require_number(raw.get("salience_score"), field_name="salience_score"),
        trust_score=_require_number(raw.get("trust_score"), field_name="trust_score"),
        decay=DecayState(
            archived=bool(decay.get("archived", False)),
            half_life_days=_require_number(
                decay.get("half_life_days"),
                field_name="decay.half_life_days",
            ),
            last_reinforced_at=_parse_dt(decay.get("last_reinforced_at")),
        ),
        retrieval=RetrievalStats(
            access_count=int(
                _require_number(
                    retrieval.get("access_count"),
                    field_name="retrieval.access_count",
                )
            ),
            last_accessed_at=_parse_dt(retrieval.get("last_accessed_at")),
        ),
        embeddings=tuple(
            EmbeddingRecord(
                key=_require_str(entry.get("key"), field_name="embeddings[].key"),
                vector=tuple(
                    _require_number(component, field_name="embeddings[].vector[]")
                    for component in _require_list(
                        entry.get("vector"),
                        field_name="embeddings[].vector",
                    )
                ),
                model=cast(str | None, entry.get("model")),
            )
            for entry in (
                _require_mapping(candidate, field_name="embeddings[]") for candidate in embeddings
            )
        ),
        metadata=cast(dict[str, JSONValue], raw.get("metadata", {})),
    )


def dump_memory(memory: MemoryAtom) -> str:
    return json.dumps(memory_payload(memory), sort_keys=True)


def load_memory(payload: str) -> MemoryAtom:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise TypeError("memory payload must decode to an object")
    return load_memory_payload(cast(Mapping[str, object], raw))


def edge_payload(edge: MemoryEdge) -> dict[str, object]:
    return {
        "edge_id": edge.edge_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "kind": edge.kind.value,
        "provenance": {
            "source_id": edge.provenance.source_id,
            "source_type": edge.provenance.source_type,
            "uri": edge.provenance.uri,
            "ingest_run_id": edge.provenance.ingest_run_id,
            "metadata": edge.provenance.metadata,
        },
        "created_at": _dt(edge.created_at),
        "weight": edge.weight,
        "metadata": edge.metadata,
    }


def load_edge_payload(raw: Mapping[str, object]) -> MemoryEdge:
    provenance = _require_mapping(raw.get("provenance"), field_name="provenance")
    created_at = _parse_dt(raw.get("created_at"))
    if created_at is None:
        raise TypeError("created_at payload must be present")

    return MemoryEdge(
        edge_id=_require_str(raw.get("edge_id"), field_name="edge_id"),
        source_id=_require_str(raw.get("source_id"), field_name="source_id"),
        target_id=_require_str(raw.get("target_id"), field_name="target_id"),
        kind=EdgeKind(_require_str(raw.get("kind"), field_name="kind")),
        provenance=Provenance(
            source_id=_require_str(provenance.get("source_id"), field_name="provenance.source_id"),
            source_type=_require_str(
                provenance.get("source_type"),
                field_name="provenance.source_type",
            ),
            uri=cast(str | None, provenance.get("uri")),
            ingest_run_id=cast(str | None, provenance.get("ingest_run_id")),
            metadata=cast(dict[str, JSONValue], provenance.get("metadata", {})),
        ),
        created_at=created_at,
        weight=_require_number(raw.get("weight"), field_name="weight"),
        metadata=cast(dict[str, JSONValue], raw.get("metadata", {})),
    )


def dump_edge(edge: MemoryEdge) -> str:
    return json.dumps(edge_payload(edge), sort_keys=True)


def load_edge(payload: str) -> MemoryEdge:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise TypeError("edge payload must decode to an object")
    return load_edge_payload(cast(Mapping[str, object], raw))


def edge_is_archived(edge: MemoryEdge) -> bool:
    archived = edge.metadata.get("archived")
    return bool(archived) if isinstance(archived, bool) else False
