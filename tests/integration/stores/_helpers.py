"""Shared fixtures and assertion helpers for store integration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from cellin.core import (
    DecayState,
    EdgeKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)

_NOW = datetime(2026, 4, 5, tzinfo=UTC)


def make_memory(memory_id: str, text: str) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=_NOW,
        observed_at=_NOW,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


def make_edge(edge_id: str, source_id: str, target_id: str, *, archived: bool) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=_NOW,
        metadata={"archived": archived},
    )


def assert_list_by_filtering(memory_store: object) -> None:
    """Seed a memory store with three tagged memories and assert all four filter combos."""
    active_atlas = replace(
        make_memory("active-atlas", "atlas memory"),
        decay=DecayState(archived=False, half_life_days=14.0),
        metadata={"topic": "atlas"},
    )
    archived_atlas = replace(
        make_memory("archived-atlas", "old atlas memory"),
        decay=DecayState(archived=True, half_life_days=14.0),
        metadata={"topic": "atlas"},
    )
    active_beta = replace(
        make_memory("active-beta", "beta memory"),
        decay=DecayState(archived=False, half_life_days=14.0),
        metadata={"topic": "beta"},
    )
    memory_store.put_many((active_atlas, archived_atlas, active_beta))  # type: ignore[union-attr]

    active_only = memory_store.list_by(archived=False)  # type: ignore[union-attr]
    assert {m.memory_id for m in active_only} == {"active-atlas", "active-beta"}

    archived_only = memory_store.list_by(archived=True)  # type: ignore[union-attr]
    assert {m.memory_id for m in archived_only} == {"archived-atlas"}

    atlas_only = memory_store.list_by(topic="atlas")  # type: ignore[union-attr]
    assert {m.memory_id for m in atlas_only} == {"active-atlas", "archived-atlas"}

    active_atlas_only = memory_store.list_by(archived=False, topic="atlas")  # type: ignore[union-attr]
    assert {m.memory_id for m in active_atlas_only} == {"active-atlas"}
