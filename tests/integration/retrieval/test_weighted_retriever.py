"""Integration tests for retrieval, ranking, and bundle assembly."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
from cellin.evals.retrieval_benchmarks import seeded_benchmark_cases
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever


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
        self._edges = list(edges)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges.append(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self._edges
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self._edges)


def _memory(
    memory_id: str,
    text: str,
    *,
    observed_at: datetime,
    salience: float,
    trust: float,
    access_count: int = 0,
    token_count: int | None = None,
) -> MemoryAtom:
    metadata = {}
    if token_count is not None:
        metadata["token_count"] = token_count

    provenance = Provenance(source_id=memory_id, source_type="fixture")
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=provenance,
        modality=Modality.TEXT,
        created_at=observed_at,
        observed_at=observed_at,
        salience_score=salience,
        trust_score=trust,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(access_count=access_count),
        metadata=metadata,
    )


def _seeded_memories() -> tuple[tuple[MemoryAtom, ...], tuple[MemoryEdge, ...]]:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    atlas_arch = _memory(
        "atlas-arch",
        "Atlas architecture uses a memory graph and weighted retrieval for planning.",
        observed_at=now - timedelta(days=7),
        salience=0.95,
        trust=0.9,
        access_count=4,
        token_count=8,
    )
    atlas_vision = _memory(
        "atlas-vision",
        "Atlas roadmap focuses on graph consolidation and memory abstractions.",
        observed_at=now - timedelta(days=60),
        salience=0.76,
        trust=0.85,
        access_count=1,
        token_count=8,
    )
    deploy_yesterday = _memory(
        "deploy-yesterday",
        "Yesterday the staging rollout completed with green checks.",
        observed_at=now - timedelta(days=1),
        salience=0.7,
        trust=0.95,
        access_count=2,
        token_count=7,
    )
    unrelated = _memory(
        "gardening-note",
        "Compost ratios and tomato pruning notes for the garden shed.",
        observed_at=now - timedelta(days=2),
        salience=0.2,
        trust=0.7,
        token_count=7,
    )

    edges = (
        MemoryEdge(
            edge_id="edge-arch-vision",
            source_id="atlas-arch",
            target_id="atlas-vision",
            kind=EdgeKind.SUPPORTS,
            provenance=Provenance(source_id="edge-arch-vision", source_type="fixture"),
            created_at=now - timedelta(days=7),
        ),
    )
    return (atlas_arch, atlas_vision, deploy_yesterday, unrelated), edges


def test_concept_profile_uses_graph_expansion_for_related_memory() -> None:
    memories, edges = _seeded_memories()
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories, edges)
    profile = get_weight_profile("concept_sensitive")
    retriever = WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )
    benchmark = seeded_benchmark_cases()[0]

    bundle = retriever.retrieve(benchmark.query, top_k=benchmark.top_k)

    assert tuple(item.memory.memory_id for item in bundle.memories) == benchmark.expected_memory_ids
    assert bundle.memories[1].factors[1].name == "graph_proximity"
    assert bundle.memories[1].factors[1].value > 0.0


def test_recency_profile_prefers_recent_memory() -> None:
    memories, edges = _seeded_memories()
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories, edges)
    profile = get_weight_profile("recency_sensitive")
    retriever = WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )
    benchmark = seeded_benchmark_cases()[1]

    bundle = retriever.retrieve(benchmark.query, top_k=benchmark.top_k)

    assert tuple(item.memory.memory_id for item in bundle.memories) == benchmark.expected_memory_ids
    assert bundle.memories[0].factors[2].name == "recency"
    assert bundle.memories[0].factors[2].value > 0.8


def test_bundle_respects_token_budget() -> None:
    memories, edges = _seeded_memories()
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories, edges)
    profile = replace(get_weight_profile("balanced"), token_budget=8)
    retriever = WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )

    bundle = retriever.retrieve("Explain the Atlas architecture and roadmap", top_k=3)

    assert len(bundle.memories) == 1
    assert bundle.memories[0].memory.memory_id == "atlas-arch"


def test_bundle_returns_empty_when_top_k_one_candidate_is_oversized() -> None:
    memories, edges = _seeded_memories()
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories, edges)
    profile = replace(get_weight_profile("balanced"), token_budget=7)
    retriever = WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )

    bundle = retriever.retrieve(
        "Atlas architecture uses a memory graph and weighted retrieval for planning.",
        top_k=1,
    )

    assert bundle.memories == ()
    assert bundle.total_score == 0.0
    assert bundle.summary is None


def test_bundle_skips_oversized_first_candidate_and_selects_in_budget_next() -> None:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    memories = (
        _memory(
            "oversized-candidate",
            "Atlas architecture weighted retrieval memory graph planning",
            observed_at=now - timedelta(days=1),
            salience=0.99,
            trust=0.99,
            access_count=9,
            token_count=20,
        ),
        _memory(
            "fits-budget",
            "Atlas architecture weighted retrieval memory graph planning",
            observed_at=now - timedelta(days=1),
            salience=0.45,
            trust=0.75,
            access_count=0,
            token_count=5,
        ),
    )
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories, ())
    profile = replace(get_weight_profile("balanced"), token_budget=6)
    retriever = WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: now,
        ),
        profile=profile,
    )

    bundle = retriever.retrieve(
        "Atlas architecture weighted retrieval memory graph planning",
        top_k=2,
    )

    assert tuple(item.memory.memory_id for item in bundle.memories) == ("fits-budget",)
    assert (
        sum(item.memory.metadata["token_count"] for item in bundle.memories) <= profile.token_budget
    )
