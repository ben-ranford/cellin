"""Integration tests for deterministic dream scheduling and rollback."""

from __future__ import annotations

import json
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
from cellin.dreaming import (
    AbstractionDreamStrategy,
    ContradictionRepairDreamStrategy,
    DeduplicationDreamStrategy,
    DreamRunner,
)
from cellin.dreaming.benchmarks import seeded_dream_benchmark_cases
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
        edges: tuple[MemoryEdge, ...] = (),
    ) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}
        self._edges = {edge.edge_id: edge for edge in edges}

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges[edge.edge_id] = edge

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self.list_edges()
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge for edge in self._edges.values() if edge.metadata.get("archived") is not True
        )


def _memory(
    memory_id: str,
    text: str,
    *,
    observed_at: datetime,
    topic: str,
    salience: float = 0.7,
    trust: float = 0.9,
    access_count: int = 0,
) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=observed_at,
        observed_at=observed_at,
        salience_score=salience,
        trust_score=trust,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(access_count=access_count),
        metadata={"topic": topic, "token_count": len(text.split())},
    )


def _retriever(memory_store: MemoryStore, graph_store: GraphStore) -> WeightedRetriever:
    profile = get_weight_profile("balanced")
    return WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )


def _fixture_memories() -> tuple[MemoryAtom, ...]:
    with open("evals/fixtures/dreaming/atlas_corpus.json", encoding="utf-8") as handle:
        raw = json.load(handle)

    return tuple(
        MemoryAtom(
            memory_id=item["memory_id"],
            kind=MemoryKind.ATOM,
            text=item["text"],
            provenance=Provenance(source_id=item["memory_id"], source_type="fixture"),
            modality=Modality.TEXT,
            created_at=datetime.fromisoformat(item["observed_at"]),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            salience_score=float(item["salience_score"]),
            trust_score=float(item["trust_score"]),
            decay=DecayState(half_life_days=14.0),
            retrieval=RetrievalStats(),
            metadata=item["metadata"],
        )
        for item in raw
    )


def test_deduplication_diff_is_machine_readable_and_reversible() -> None:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    memories = (
        _memory(
            "atlas-plan-a",
            "Atlas planning uses weighted retrieval for memory search.",
            observed_at=now - timedelta(days=2),
            topic="atlas",
            access_count=2,
        ),
        _memory(
            "atlas-plan-b",
            "Atlas planning uses weighted retrieval for memory search.",
            observed_at=now - timedelta(days=1),
            topic="atlas",
            access_count=1,
        ),
    )
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories)
    runner = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"deduplication": DeduplicationDreamStrategy()},
    )

    result = runner.run_strategy("deduplication", at=now)

    assert result is not None
    serialized = result.diff.to_dict()
    assert serialized["memory_changes"]
    assert serialized["edge_changes"]
    archived_memories = [memory for memory in memory_store.list() if memory.decay.archived]
    assert len(archived_memories) == 1

    runner.rollback(result.diff)

    assert all(not memory.decay.archived for memory in memory_store.list())
    assert graph_store.list_edges() == ()


def test_deduplication_rejects_false_merges_when_numeric_claims_conflict() -> None:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    memories = (
        _memory(
            "atlas-capacity-12",
            "Atlas cluster is active in 12 regions with stable failover.",
            observed_at=now - timedelta(days=2),
            topic="atlas",
        ),
        _memory(
            "atlas-capacity-15",
            "Atlas cluster is active in 15 regions with stable failover.",
            observed_at=now - timedelta(days=1),
            topic="atlas",
        ),
    )
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories)
    strategy = DeduplicationDreamStrategy()

    result = strategy.execute(graph_store, memory_store, at=now)

    assert result is None
    assert all(not memory.decay.archived for memory in memory_store.list())


def test_contradiction_repair_creates_edge_and_down_ranks_older_claim() -> None:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    memories = (
        _memory(
            "atlas-rollout-green",
            "Atlas rollout is green and stable in staging.",
            observed_at=now - timedelta(days=2),
            topic="atlas-rollout",
            trust=0.95,
        ),
        _memory(
            "atlas-rollout-rollback",
            "Atlas rollout was rolled back after failures in staging.",
            observed_at=now - timedelta(days=1),
            topic="atlas-rollout",
            trust=0.92,
        ),
    )
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories)
    strategy = ContradictionRepairDreamStrategy()

    result = strategy.execute(graph_store, memory_store, at=now)

    assert result is not None
    older = memory_store.get("atlas-rollout-green")
    newer = memory_store.get("atlas-rollout-rollback")
    assert older is not None and newer is not None
    assert older.trust_score < 0.95
    assert newer.salience_score > 0.7
    contradiction_edge = graph_store.list_edges()[0]
    assert contradiction_edge.kind is EdgeKind.CONTRADICTS


def test_abstraction_benchmark_improves_retrieval_for_combined_queries() -> None:
    memories = _fixture_memories()
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories)
    retriever = _retriever(memory_store, graph_store)
    benchmark = seeded_dream_benchmark_cases()[0]
    before = retriever.retrieve(benchmark.query, top_k=1)
    runner = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"abstraction": AbstractionDreamStrategy()},
    )

    result = runner.run_strategy("abstraction", at=datetime(2026, 4, 4, tzinfo=UTC))
    after = retriever.retrieve(benchmark.query, top_k=1)

    assert result is not None
    assert after.memories[0].memory.memory_id == benchmark.expected_top_memory_id_after
    assert after.total_score >= before.total_score + benchmark.minimum_score_gain


def test_abstraction_summary_token_count_matches_rendered_summary() -> None:
    now = datetime(2026, 4, 4, tzinfo=UTC)
    memories = (
        _memory(
            "atlas-summary-low",
            "Atlas keeps a durable memory graph.",
            observed_at=now - timedelta(days=2),
            topic="atlas",
            salience=0.4,
        ),
        _memory(
            "atlas-summary-high",
            "Atlas retrieval favors higher-salience evidence first.",
            observed_at=now - timedelta(days=1),
            topic="atlas",
            salience=0.9,
        ),
    )
    memory_store = InMemoryMemoryStore(memories)
    graph_store = InMemoryGraphStore(memories)
    strategy = AbstractionDreamStrategy()

    result = strategy.execute(graph_store, memory_store, at=now)

    assert result is not None
    created_memory_id = result.artifact.affected_memory_ids[0]
    summary_memory = memory_store.get(created_memory_id)
    assert summary_memory is not None
    assert summary_memory.metadata["token_count"] == len(summary_memory.text.split())
