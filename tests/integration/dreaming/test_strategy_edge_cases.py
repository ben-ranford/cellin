"""Additional branch coverage for dream strategy helpers and no-op cases."""

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
from cellin.dreaming.strategies import (
    AbstractionDreamStrategy,
    ContradictionRepairDreamStrategy,
    DeduplicationDreamStrategy,
    _group_active_memories_by_topic,
    _MutationOutcome,
    _similarity,
    _string_list,
)


def _memory(
    memory_id: str,
    text: str,
    *,
    topic: str,
    observed_at: datetime,
    archived: bool = False,
    trust: float = 0.9,
) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=observed_at,
        observed_at=observed_at,
        salience_score=0.7,
        trust_score=trust,
        decay=DecayState(archived=archived, half_life_days=14.0),
        retrieval=RetrievalStats(),
        metadata={"topic": topic},
    )


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
    def __init__(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}
        self._edges: dict[str, MemoryEdge] = {}

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges[edge.edge_id] = edge

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self._edges.values()
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self._edges.values())


def test_strategy_helpers_handle_empty_tokens_string_lists_and_archived_grouping() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    blank_left = _memory("blank-left", "!!!", topic="atlas", observed_at=now)
    blank_right = _memory("blank-right", "???", topic="atlas", observed_at=now)
    grouped = _group_active_memories_by_topic(
        InMemoryMemoryStore(
            (
                _memory("active", "Atlas note", topic="atlas", observed_at=now),
                _memory(
                    "archived", "Atlas old note", topic="atlas", observed_at=now, archived=True
                ),
            )
        )
    )

    assert _similarity(blank_left, blank_right) == 0.0
    assert _string_list("not-a-list") == []
    assert [memory.memory_id for memory in grouped["atlas"]] == ["active"]


def test_deduplication_skips_single_member_topics_and_archived_duplicates() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    strategy = DeduplicationDreamStrategy(similarity_threshold=0.5)
    memory_store = InMemoryMemoryStore(())
    graph_store = InMemoryGraphStore(())
    outcome = _MutationOutcome.empty()

    strategy._merge_topic_members(
        members=[_memory("solo", "Atlas note", topic="atlas", observed_at=now)],
        at=now,
        graph_store=graph_store,
        memory_store=memory_store,
        outcome=outcome,
    )

    canonical = _memory("canonical", "Atlas note", topic="atlas", observed_at=now, trust=1.0)
    duplicate = _memory(
        "duplicate",
        "Atlas note",
        topic="atlas",
        observed_at=now,
        archived=True,
        trust=0.5,
    )
    strategy._merge_pair(
        left=canonical,
        right=duplicate,
        at=now,
        graph_store=graph_store,
        memory_store=memory_store,
        outcome=outcome,
    )

    assert outcome.pairs == []
    assert graph_store.list_edges() == ()


def test_contradiction_repair_skips_non_conflicts_and_existing_edges() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    strategy = ContradictionRepairDreamStrategy()
    older = _memory("older", "Atlas rollout is green.", topic="atlas", observed_at=now)
    newer = _memory("newer", "Atlas rollout is stable.", topic="atlas", observed_at=now)

    assert (
        strategy.execute(
            InMemoryGraphStore((older, newer)),
            InMemoryMemoryStore((older, newer)),
            at=now,
        )
        is None
    )

    conflict_older = _memory(
        "conflict-older",
        "Atlas rollout is green.",
        topic="atlas-rollout",
        observed_at=now,
    )
    conflict_newer = _memory(
        "conflict-newer",
        "Atlas rollout was rolled back.",
        topic="atlas-rollout",
        observed_at=now,
    )
    edge_id = strategy._contradiction_edge_id(older=conflict_older, newer=conflict_newer)
    outcome = _MutationOutcome.empty()
    strategy._repair_pair(
        older=conflict_older,
        newer=conflict_newer,
        at=now,
        graph_store=InMemoryGraphStore((conflict_older, conflict_newer)),
        memory_store=InMemoryMemoryStore((conflict_older, conflict_newer)),
        existing_edges={
            edge_id: MemoryEdge(
                edge_id=edge_id,
                source_id=conflict_older.memory_id,
                target_id=conflict_newer.memory_id,
                kind=EdgeKind.CONTRADICTS,
                provenance=Provenance(source_id=edge_id, source_type="fixture"),
                created_at=now,
            )
        },
        outcome=outcome,
    )

    assert outcome.pairs == []


def test_abstraction_returns_none_when_topics_do_not_qualify() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    singleton = _memory("solo", "Solo note", topic="solo", observed_at=now)
    summary = MemoryAtom(
        memory_id="dream-atlas",
        kind=MemoryKind.DREAM,
        text="Atlas summary.",
        provenance=Provenance(source_id="dream-atlas", source_type="dream"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        metadata={"topic": "atlas"},
    )
    atlas_a = _memory("atlas-a", "Atlas note one", topic="atlas", observed_at=now)
    atlas_b = _memory("atlas-b", "Atlas note two", topic="atlas", observed_at=now)
    memory_store = InMemoryMemoryStore((singleton, summary, atlas_a, atlas_b))
    graph_store = InMemoryGraphStore((singleton, summary, atlas_a, atlas_b))

    result = AbstractionDreamStrategy().execute(graph_store, memory_store, at=now)

    assert result is None
