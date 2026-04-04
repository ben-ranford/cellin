"""Load version-controlled corpora for deterministic evals."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import cast

from cellin.core import DecayState, MemoryAtom, MemoryKind, Modality, Provenance, RetrievalStats
from cellin.core.models import JSONValue
from cellin.ingest import ArtifactEnvelope


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(relative_path: str) -> JSONValue:
    with (_repo_root() / relative_path).open(encoding="utf-8") as handle:
        return cast(JSONValue, json.load(handle))


def load_memory_records(relative_path: str) -> tuple[MemoryAtom, ...]:
    raw = _load_json(relative_path)
    assert isinstance(raw, list)
    memories: list[MemoryAtom] = []
    for item in raw:
        assert isinstance(item, dict)
        memory_id = item["memory_id"]
        observed_at = item["observed_at"]
        text = item["text"]
        metadata = item["metadata"]
        salience_score = item["salience_score"]
        trust_score = item["trust_score"]
        access_count = item.get("access_count", 0)
        assert isinstance(memory_id, str)
        assert isinstance(observed_at, str)
        assert isinstance(text, str)
        assert isinstance(metadata, dict)
        assert isinstance(salience_score, int | float)
        assert isinstance(trust_score, int | float)
        assert isinstance(access_count, int)
        memories.append(
            MemoryAtom(
                memory_id=memory_id,
                kind=MemoryKind.ATOM,
                text=text,
                provenance=Provenance(source_id=memory_id, source_type="eval-corpus"),
                modality=Modality.TEXT,
                created_at=datetime.fromisoformat(observed_at),
                observed_at=datetime.fromisoformat(observed_at),
                salience_score=float(salience_score),
                trust_score=float(trust_score),
                decay=DecayState(half_life_days=14.0),
                retrieval=RetrievalStats(access_count=access_count),
                metadata=dict(metadata),
            )
        )
    return tuple(memories)


def load_memory_corpus(name: str) -> tuple[MemoryAtom, ...]:
    return load_memory_records(f"evals/corpora/{name}.json")


def load_envelope_corpus(name: str) -> tuple[ArtifactEnvelope, ...]:
    raw = _load_json(f"evals/corpora/{name}.json")
    assert isinstance(raw, list)
    envelopes: list[ArtifactEnvelope] = []
    for item in raw:
        assert isinstance(item, dict)
        modality = item["modality"]
        observed_at = item["observed_at"]
        payload = item["payload"]
        metadata = item["metadata"]
        assert isinstance(modality, str)
        assert isinstance(observed_at, str)
        assert isinstance(metadata, dict)
        assert isinstance(payload, str | dict | list)
        envelopes.append(
            ArtifactEnvelope(
                envelope_id=str(item["envelope_id"]),
                modality=Modality(modality),
                payload=payload,
                source_id=str(item["source_id"]),
                source_type=str(item["source_type"]),
                observed_at=datetime.fromisoformat(observed_at),
                metadata=dict(metadata),
            )
        )
    return tuple(envelopes)
