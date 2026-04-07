"""Integration tests for retrieval candidate generation semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest

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
    VectorMatch,
    VectorStore,
)
from cellin.retrieval import RetrievalCandidateGenerator


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


def _memory_store(memories: tuple[MemoryAtom, ...]) -> MemoryStore:
    indexed = {memory.memory_id: memory for memory in memories}
    store = create_autospec(MemoryStore, instance=True)
    store.list.return_value = memories
    store.get.side_effect = indexed.get
    return store


def _graph_store(
    memories: tuple[MemoryAtom, ...],
    edges: tuple[MemoryEdge, ...],
) -> GraphStore:
    indexed = {memory.memory_id: memory for memory in memories}
    graph = create_autospec(GraphStore, instance=True)
    graph.get_memory.side_effect = indexed.get
    graph.neighbors.side_effect = lambda memory_id: tuple(
        edge for edge in edges if edge.source_id == memory_id or edge.target_id == memory_id
    )
    return graph


class _FakeVectorStore(VectorStore):
    def __init__(self, matches: tuple[tuple[str, float], ...]) -> None:
        self._matches = tuple(matches)

    def upsert(self, memory_id: str, text: str) -> None:
        # No-op: this fake vector store only needs to satisfy the interface.
        del memory_id, text

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        del query
        ordered = sorted(
            self._matches,
            key=lambda item: (-item[1], item[0]),
        )
        return tuple(
            VectorMatch(memory_id=memory_id, score=round(score, 6))
            for memory_id, score in ordered[: max(0, limit)]
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
        memory_store=_memory_store(memories),
        graph_store=_graph_store(memories, edges),
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
        memory_store=_memory_store(memories),
        graph_store=_graph_store(memories, edges),
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
        memory_store=_memory_store(memories),
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
        memory_store=_memory_store(memories),
        graph_store=None,
    )

    assert generator.collect("atlas retrieval", limit=0) == ()


def test_collect_prefers_hybrid_lexical_and_vector_seeding_with_graph_expansion() -> None:
    memories = (
        _memory("lexical", "Atlas architecture and retrieval"),
        _memory("vector-primary", "Unrelated vector-only signal"),
        _memory("graph-neighbor", "Graph neighbor to vector primary"),
        _memory("inactive", "no relevance"),
    )
    edges = (_edge("vector-to-graph", "vector-primary", "graph-neighbor"),)
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store(memories),
        graph_store=_graph_store(memories, edges),
        vector_store=_FakeVectorStore(
            (
                ("vector-primary", 0.9),
                ("inactive", 0.4),
            )
        ),
    )

    collected = generator.collect("Atlas", limit=3)

    assert tuple(memory.memory_id for memory in collected) == (
        "lexical",
        "vector-primary",
        "graph-neighbor",
    )
    assert collected[0].metadata["graph_distance"] == 0
    assert collected[1].metadata["graph_distance"] == 0
    assert collected[1].metadata["vector_score"] == pytest.approx(0.9)
    assert collected[2].metadata["graph_distance"] == 1


def test_collect_uses_vector_candidates_when_lexical_candidates_are_absent() -> None:
    memories = (
        _memory("seed-vector", "gamma delta"),
        _memory("seed-lex", "alpha beta"),
        _memory("vector-neighbor", "epsilon"),
    )
    edges = (_edge("vector-neighbor-edge", "seed-vector", "vector-neighbor"),)
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store(memories),
        graph_store=_graph_store(memories, edges),
        vector_store=_FakeVectorStore(
            (
                ("seed-vector", 0.7),
                ("seed-lex", 0.4),
            )
        ),
        lexical_limit=1,
    )

    collected = generator.collect("atlas retrieval query", limit=3)

    assert tuple(memory.memory_id for memory in collected) == (
        "seed-vector",
        "seed-lex",
        "vector-neighbor",
    )
    assert all("vector_score" in memory.metadata for memory in collected[:2])
    assert collected[0].metadata["vector_score"] == pytest.approx(0.7)


def test_seed_candidates_returns_empty_for_non_positive_limit() -> None:
    memories = (_memory("seed", "Atlas retrieval graph"),)
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store(memories),
        graph_store=None,
    )

    assert generator._seed_candidates("Atlas retrieval", list(memories), (), 0) == []


def test_rank_by_vector_seed_skips_matches_not_present_in_active_memories() -> None:
    memories = (_memory("known", "Atlas retrieval graph"),)
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store(memories),
        graph_store=None,
        vector_store=_FakeVectorStore((("missing", 0.9), ("known", 0.6))),
    )

    ranked = generator._rank_by_vector_seed("Atlas retrieval", memories)

    assert tuple(memory.memory_id for memory in ranked) == ("known",)
    assert ranked[0].metadata["vector_score"] == pytest.approx(0.6)


def test_candidate_index_merges_duplicate_seed_metadata() -> None:
    base = _memory("seed", "Atlas retrieval graph")
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store((base,)),
        graph_store=None,
    )

    merged = generator._candidate_index(
        [
            replace(base, metadata={"graph_distance": 0}),
            replace(base, metadata={"vector_score": 0.84}),
        ]
    )

    assert merged["seed"].metadata == {"graph_distance": 0, "vector_score": 0.84}


def test_collect_includes_graph_neighbors_loaded_from_memory_store_lookup() -> None:
    seed = _memory("seed", "Atlas retrieval graph")
    duplicate_seed = replace(seed, metadata={"duplicate": True})
    neighbor = _memory("graph-neighbor", "Neighbor resolved from the memory store")
    store = create_autospec(MemoryStore, instance=True)
    store.list.return_value = (seed, duplicate_seed)
    store.get.side_effect = {"seed": seed, "graph-neighbor": neighbor}.get

    graph = create_autospec(GraphStore, instance=True)
    graph.get_memory.return_value = None
    graph.neighbors.side_effect = lambda memory_id: (
        (_edge("seed-to-neighbor", "seed", "graph-neighbor"),) if memory_id == "seed" else ()
    )

    generator = RetrievalCandidateGenerator(
        memory_store=store,
        graph_store=graph,
    )

    collected = generator.collect("Atlas retrieval", limit=2)

    assert tuple(memory.memory_id for memory in collected) == ("seed", "graph-neighbor")
    assert collected[1].metadata["graph_distance"] == 1
