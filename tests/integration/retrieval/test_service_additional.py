"""Additional retrieval coverage for fallback lookups and budget guards."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import create_autospec

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
    ScoredMemory,
)
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever


def _memory(memory_id: str, text: str, *, token_count: int | None = 3) -> MemoryAtom:
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
        metadata={"token_count": token_count} if token_count is not None else {},
    )


def _edge(edge_id: str, source_id: str, target_id: str) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
    )


def test_collect_falls_back_to_memory_store_when_graph_store_has_no_memory() -> None:
    seed = _memory("seed", "Atlas retrieval graph")
    neighbor = _memory("neighbor", "Atlas retrieval support")
    memories = {seed.memory_id: seed, neighbor.memory_id: neighbor}
    memory_store = create_autospec(MemoryStore, instance=True)
    memory_store.list.return_value = (seed, neighbor)
    memory_store.get.side_effect = memories.get
    graph_store = create_autospec(GraphStore, instance=True)
    graph_store.neighbors.return_value = (_edge("seed-neighbor", "seed", "neighbor"),)
    graph_store.get_memory.return_value = None
    generator = RetrievalCandidateGenerator(memory_store=memory_store, graph_store=graph_store)

    collected = generator.collect("", limit=2)

    assert tuple(memory.memory_id for memory in collected) == ("seed", "neighbor")


def test_retriever_fit_to_budget_returns_empty_when_budget_is_non_positive() -> None:
    profile = get_weight_profile("balanced")
    retriever = WeightedRetriever(
        candidate_generator=create_autospec(RetrievalCandidateGenerator, instance=True),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
    )

    assert retriever._fit_to_budget((), token_budget=0) == ()


def test_retriever_returns_empty_for_non_positive_top_k() -> None:
    profile = get_weight_profile("balanced")
    retriever = WeightedRetriever(
        candidate_generator=create_autospec(RetrievalCandidateGenerator, instance=True),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
    )

    assert retriever.retrieve("Atlas query", top_k=0).memories == ()
    assert retriever.retrieve("Atlas query", top_k=-2).memories == ()


def test_fit_to_budget_treats_negative_token_count_as_minimum_one() -> None:
    profile = get_weight_profile("balanced")
    retriever = WeightedRetriever(
        candidate_generator=create_autospec(RetrievalCandidateGenerator, instance=True),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
    )
    item_one = ScoredMemory(
        memory=_memory("negative", "negative token count", token_count=-4),
        score=1.0,
    )
    item_two = ScoredMemory(
        memory=_memory("positive", "positive token count", token_count=3),
        score=0.8,
    )
    selected = retriever._fit_to_budget((item_one, item_two), token_budget=3)
    assert selected == (item_one,)
