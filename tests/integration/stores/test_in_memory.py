"""Coverage for production in-memory stores."""

from __future__ import annotations

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
from cellin.stores import InMemoryGraphStore, InMemoryMemoryStore


def _memory(memory_id: str, text: str) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        observed_at=datetime(2026, 4, 5, tzinfo=UTC),
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


def _edge(edge_id: str, source_id: str, target_id: str, archived: bool) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        metadata={"archived": archived},
    )


def test_in_memory_memory_store_preserves_order_and_updates_entries() -> None:
    first = _memory("atlas-1", "Atlas one")
    duplicate = _memory("atlas-1", "Atlas one revised")
    second = _memory("atlas-2", "Atlas two")

    store = InMemoryMemoryStore()
    store.put_many((first, second))
    store.put(duplicate)

    assert store.get("atlas-1") == duplicate
    assert store.list() == (duplicate, second)


def test_in_memory_graph_store_handles_memories_edges_and_archived_filtering() -> None:
    active = _edge("edge-active", "atlas-1", "atlas-2", archived=False)
    archived = _edge("edge-archived", "atlas-1", "atlas-3", archived=True)

    graph_store = InMemoryGraphStore(
        memories=(_memory("atlas-1", "Atlas one"), _memory("atlas-2", "Atlas two")),
        edges=(active, archived),
    )

    assert graph_store.get_memory("atlas-1").memory_id == "atlas-1"
    assert graph_store.neighbors("atlas-1") == (active,)
    assert graph_store.list_edges() == (active,)

    graph_store.upsert_edges(())
    graph_store.upsert_edge(_edge("edge-revision", "atlas-2", "atlas-3", archived=False))

    assert {edge.edge_id for edge in graph_store.neighbors("atlas-2")} == {
        "edge-revision",
        "edge-active",
    }


def test_in_memory_graph_store_normalizes_integer_archived_markers() -> None:
    active = _edge("edge-active", "atlas-1", "atlas-2", archived=0)
    archived = _edge("edge-archived", "atlas-1", "atlas-3", archived=1)

    graph_store = InMemoryGraphStore(
        memories=(_memory("atlas-1", "Atlas one"), _memory("atlas-2", "Atlas two")),
        edges=(active, archived),
    )

    assert graph_store.neighbors("atlas-1") == (active,)
    assert graph_store.list_edges() == (active,)


def test_in_memory_graph_store_detects_shared_memory_store_reference() -> None:
    memory_store = InMemoryMemoryStore((_memory("atlas-1", "Atlas one"),))
    graph_store = InMemoryGraphStore(memories=(memory_store.list()[0],))
    graph_store._memory_store = memory_store

    assert graph_store.shares_memory_store(memory_store) is True
