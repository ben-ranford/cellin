"""Integration tests for retrieval candidate generation semantics."""

from __future__ import annotations

from datetime import UTC, datetime

from cellin.core import (
    DecayState,
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.retrieval import RetrievalCandidateGenerator


class InMemoryMemoryStore(MemoryStore):
    def __init__(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}

    def put(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self._memories.values())


class InMemoryGraphStore(GraphStore):
    def __init__(
        self,
        memories: tuple[MemoryAtom, ...],
        edges: tuple[MemoryEdge, ...],
    ) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}
        self._edges = edges

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges = (*self._edges, edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self._edges
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._edges


def _memory(
    memory_id: str,
    text: str,
    *,
    archived: bool = False,
) -> MemoryAtom:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        salience_score=0.7,
        trust_score=0.9,
        decay=DecayState(half_life_days=14.0, archived=archived),
        retrieval=RetrievalStats(),
        metadata={},
    )


def _edge(edge_id: str, source_id: str, target_id: str) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 4, tzinfo=UTC),
    )


def test_collect_filters_archived_memories_and_archived_graph_neighbors() -> None:
    memories = (
        _memory("seed", "Atlas retrieval graph"),
        _memory("active-neighbor", "Completely unrelated memory"),
        _memory("archived-seed", "Atlas retrieval archived", archived=True),
        _memory("archived-neighbor", "Archived memory linked from graph", archived=True),
        _memory("fallback", "Another unrelated memory"),
    )
    edges = (
        _edge("seed-to-archived", "seed", "archived-neighbor"),
        _edge("seed-to-active", "seed", "active-neighbor"),
    )
    generator = RetrievalCandidateGenerator(
        memory_store=InMemoryMemoryStore(memories),
        graph_store=InMemoryGraphStore(memories, edges),
    )

    collected = generator.collect("Atlas retrieval", limit=4)

    collected_ids = tuple(memory.memory_id for memory in collected)
    assert "archived-seed" not in collected_ids
    assert "archived-neighbor" not in collected_ids
    assert collected_ids == ("seed", "active-neighbor", "fallback")
    assert collected[0].metadata["graph_distance"] == 0
    assert collected[1].metadata["graph_distance"] == 1
    assert "graph_distance" not in collected[2].metadata


def test_collect_orders_graph_expansions_by_ranked_seed_not_insertion_order() -> None:
    memories = (
        _memory("seed", "alpha beta gamma"),
        _memory("lower-neighbor", "alpha"),
        _memory("higher-neighbor", "alpha beta"),
    )
    edges = (
        _edge("seed-to-lower", "seed", "lower-neighbor"),
        _edge("seed-to-higher", "seed", "higher-neighbor"),
    )
    generator = RetrievalCandidateGenerator(
        memory_store=InMemoryMemoryStore(memories),
        graph_store=InMemoryGraphStore(memories, edges),
        lexical_limit=1,
    )

    collected = generator.collect("alpha beta gamma", limit=3)

    assert tuple(memory.memory_id for memory in collected) == (
        "seed",
        "higher-neighbor",
        "lower-neighbor",
    )
    assert collected[1].metadata["graph_distance"] == 1
    assert collected[2].metadata["graph_distance"] == 1


def test_collect_fallback_and_limit_semantics_when_no_lexical_seed_matches() -> None:
    memories = (
        _memory("m1", "first memory"),
        _memory("m2", "second memory"),
        _memory("m3", "third memory"),
        _memory("m4", "fourth memory"),
    )
    generator = RetrievalCandidateGenerator(
        memory_store=InMemoryMemoryStore(memories),
        graph_store=None,
        lexical_limit=2,
    )

    collected = generator.collect("query-without-overlap", limit=3)

    assert tuple(memory.memory_id for memory in collected) == ("m1", "m2", "m3")
    assert collected[0].metadata["graph_distance"] == 0
    assert collected[1].metadata["graph_distance"] == 0
    assert "graph_distance" not in collected[2].metadata


def test_collect_returns_empty_when_limit_is_zero() -> None:
    memories = (_memory("seed", "atlas retrieval graph"),)
    generator = RetrievalCandidateGenerator(
        memory_store=InMemoryMemoryStore(memories),
        graph_store=None,
    )

    assert generator.collect("atlas retrieval", limit=0) == ()
