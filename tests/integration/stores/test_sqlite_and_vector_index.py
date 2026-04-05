"""Additional coverage for SQLite stores and the in-memory vector index."""

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
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore


def _memory(memory_id: str, text: str) -> MemoryAtom:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


def _edge(edge_id: str, source_id: str, target_id: str, *, archived: bool) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        metadata={"archived": archived},
    )


def test_sqlite_store_handles_empty_batches_missing_rows_and_batched_memory_upserts(
    tmp_path,
) -> None:
    database_path = tmp_path / "cellin.sqlite"
    memory_store = SQLiteMemoryStore(str(database_path))
    graph_store = SQLiteGraphStore(str(database_path))
    memory = _memory("atlas-1", "Atlas memory")

    memory_store.put_many(())
    graph_store.upsert_edges(())

    assert memory_store.get("missing") is None
    assert graph_store.list_edges() == ()

    graph_store.upsert_memories((memory,))

    assert graph_store.get_memory(memory.memory_id) == memory


def test_sqlite_store_filters_archived_edges_and_vector_index_handles_empty_text(
    tmp_path,
) -> None:
    database_path = tmp_path / "graph.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    active = _edge("active-edge", "atlas-1", "atlas-2", archived=False)
    archived = _edge("archived-edge", "atlas-1", "atlas-3", archived=True)

    graph_store.upsert_edge(active)
    graph_store.upsert_edge(archived)

    assert graph_store.neighbors("atlas-1") == (active,)
    assert graph_store.list_edges() == (active,)

    vector_index = InMemoryVectorIndex()
    vector_index.upsert("blank", "")

    assert vector_index.search("", limit=1)[0].score == 0.0
