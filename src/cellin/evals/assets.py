"""Load version-controlled corpora for deterministic evals."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from cellin.core import DecayState, MemoryAtom, MemoryKind, Modality, Provenance, RetrievalStats
from cellin.core.models import JSONValue
from cellin.ingest import ArtifactEnvelope


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _evals_root() -> Path:
    return _repo_root() / "evals"


def _corpora_root() -> Path:
    return _evals_root() / "corpora"


def _resolve_within_root(path: Path, root: Path, *, descriptor: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"{descriptor} resolves outside {resolved_root}")
    return resolved_path


def _load_json(relative_path: str) -> JSONValue:
    path = _resolve_within_root(
        _repo_root() / relative_path,
        _evals_root(),
        descriptor=f"Eval asset path {relative_path!r}",
    )
    with path.open(encoding="utf-8") as handle:
        return cast(JSONValue, json.load(handle))


def _load_corpus_json(name: str) -> JSONValue:
    path = _resolve_within_root(
        _corpora_root() / f"{name}.json",
        _corpora_root(),
        descriptor=f"Eval corpus name {name!r}",
    )
    with path.open(encoding="utf-8") as handle:
        return cast(JSONValue, json.load(handle))


def _as_corpus_list(raw: JSONValue, *, loader_name: str) -> list[JSONValue]:
    if not isinstance(raw, list):
        raise ValueError(f"{loader_name} corpus must be a JSON list")
    return raw


def _require_type(
    item: dict[str, JSONValue],
    key: str,
    expected: type[Any] | tuple[type[Any], ...],
    *,
    context: str,
) -> Any:
    if key not in item:
        raise ValueError(f"{context} missing required field {key!r}")
    value = item[key]
    if not isinstance(value, expected):
        raise ValueError(f"{context}.{key} has invalid type {type(value).__name__}")
    return value


def _require_number(item: dict[str, JSONValue], key: str, *, context: str) -> float:
    value = _require_type(item, key, (int, float), context=context)
    if isinstance(value, bool):
        raise ValueError(f"{context}.{key} has invalid type bool")
    return float(value)


def _parse_iso_datetime(value: str, *, context: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO-8601 datetime string") from exc


def _load_memory_atoms(raw: JSONValue, *, context: str) -> tuple[MemoryAtom, ...]:
    records = _as_corpus_list(raw, loader_name=context)
    memories: list[MemoryAtom] = []
    for index, raw_item in enumerate(records):
        item_context = f"{context}[{index}]"
        if not isinstance(raw_item, dict):
            raise ValueError(f"{item_context} must be a JSON object")
        item = raw_item
        memory_id = _require_type(item, "memory_id", str, context=item_context)
        observed_at_raw = _require_type(item, "observed_at", str, context=item_context)
        text = _require_type(item, "text", str, context=item_context)
        metadata = _require_type(item, "metadata", dict, context=item_context)
        salience_score = _require_number(item, "salience_score", context=item_context)
        trust_score = _require_number(item, "trust_score", context=item_context)
        access_count_raw = item.get("access_count", 0)
        if not isinstance(access_count_raw, int) or isinstance(access_count_raw, bool):
            raise ValueError(
                f"{item_context}.access_count has invalid type {type(access_count_raw).__name__}"
            )
        observed_at = _parse_iso_datetime(observed_at_raw, context=f"{item_context}.observed_at")
        memories.append(
            MemoryAtom(
                memory_id=memory_id,
                kind=MemoryKind.ATOM,
                text=text,
                provenance=Provenance(source_id=memory_id, source_type="eval-corpus"),
                modality=Modality.TEXT,
                created_at=observed_at,
                observed_at=observed_at,
                salience_score=salience_score,
                trust_score=trust_score,
                decay=DecayState(half_life_days=14.0),
                retrieval=RetrievalStats(access_count=access_count_raw),
                metadata=dict(metadata),
            )
        )
    return tuple(memories)


def load_memory_records(relative_path: str) -> tuple[MemoryAtom, ...]:
    return _load_memory_atoms(_load_json(relative_path), context="memory corpus")


def _load_envelopes(raw: JSONValue, *, context: str) -> tuple[ArtifactEnvelope, ...]:
    records = _as_corpus_list(raw, loader_name=context)
    envelopes: list[ArtifactEnvelope] = []
    for index, raw_item in enumerate(records):
        item_context = f"{context}[{index}]"
        if not isinstance(raw_item, dict):
            raise ValueError(f"{item_context} must be a JSON object")
        item = raw_item
        envelope_id = _require_type(item, "envelope_id", str, context=item_context)
        modality_name = _require_type(item, "modality", str, context=item_context)
        source_id = _require_type(item, "source_id", str, context=item_context)
        source_type = _require_type(item, "source_type", str, context=item_context)
        observed_at_raw = _require_type(item, "observed_at", str, context=item_context)
        metadata = _require_type(item, "metadata", dict, context=item_context)
        payload = _require_type(
            item,
            "payload",
            (str, dict, list),
            context=item_context,
        )
        observed_at = _parse_iso_datetime(observed_at_raw, context=f"{item_context}.observed_at")
        try:
            modality = Modality(modality_name)
        except ValueError as exc:
            raise ValueError(
                f"{item_context}.modality has unknown value {modality_name!r}"
            ) from exc
        envelopes.append(
            ArtifactEnvelope(
                envelope_id=envelope_id,
                modality=modality,
                payload=payload,
                source_id=source_id,
                source_type=source_type,
                observed_at=observed_at,
                metadata=dict(metadata),
            )
        )
    return tuple(envelopes)


def load_memory_corpus(name: str) -> tuple[MemoryAtom, ...]:
    return _load_memory_atoms(_load_corpus_json(name), context="memory corpus")


def load_envelope_corpus(name: str) -> tuple[ArtifactEnvelope, ...]:
    return _load_envelopes(_load_corpus_json(name), context="envelope corpus")
