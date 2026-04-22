"""Additional branch coverage for dream strategy helpers and no-op cases."""

from __future__ import annotations

from datetime import UTC, datetime

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

    assert _similarity(blank_left, blank_right) == pytest.approx(0.0)
    assert _string_list("not-a-list") == []
    assert [memory.memory_id for memory in grouped["atlas"]] == ["active"]


def test_deduplication_skips_single_member_topics_and_archived_duplicates() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    strategy = DeduplicationDreamStrategy(similarity_threshold=0.5)
    memory_store = InMemoryMemoryStore(())
    graph_store = InMemoryGraphStore(())
    outcome = _MutationOutcome.empty()

    solo = _memory("solo", "Atlas note", topic="atlas", observed_at=now)
    strategy._merge_topic_members(
        members=[solo],
        at=now,
        graph_store=graph_store,
        memory_store=memory_store,
        memory_index={solo.memory_id: solo},
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
        memory_index={canonical.memory_id: canonical, duplicate.memory_id: duplicate},
        outcome=outcome,
    )

    assert outcome.pairs == []
    assert graph_store.list_edges() == ()


def test_deduplication_skips_members_archived_earlier_in_same_run() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    strategy = DeduplicationDreamStrategy(similarity_threshold=0.5)
    canonical = _memory("canonical", "atlas alpha beta", topic="atlas", observed_at=now, trust=1.0)
    duplicate = _memory(
        "duplicate",
        "atlas alpha beta gamma epsilon",
        topic="atlas",
        observed_at=now,
        trust=0.9,
    )
    newer = _memory(
        "newer",
        "atlas gamma epsilon",
        topic="atlas",
        observed_at=now,
        trust=0.8,
    )
    memory_store = InMemoryMemoryStore((canonical, duplicate, newer))
    graph_store = InMemoryGraphStore((canonical, duplicate, newer))
    outcome = _MutationOutcome.empty()

    strategy._merge_topic_members(
        members=[canonical, duplicate, newer],
        at=now,
        graph_store=graph_store,
        memory_store=memory_store,
        memory_index={
            canonical.memory_id: canonical,
            duplicate.memory_id: duplicate,
            newer.memory_id: newer,
        },
        outcome=outcome,
    )

    canonical_after = memory_store.get("canonical")
    duplicate_after = memory_store.get("duplicate")
    newer_after = memory_store.get("newer")

    assert canonical_after is not None
    assert duplicate_after is not None
    assert newer_after is not None
    assert duplicate_after.decay.archived is True
    assert newer_after.decay.archived is False
    assert outcome.pairs == [("duplicate", "canonical")]


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


def test_contradiction_repair_iterates_only_forward_unique_pairs() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    calls: list[tuple[str, str]] = []

    class _CapturingContradictionStrategy(ContradictionRepairDreamStrategy):
        def _repair_pair(
            self,
            *,
            older: MemoryAtom,
            newer: MemoryAtom,
            at: datetime,
            graph_store: GraphStore,
            memory_store: MemoryStore,
            existing_edges: dict[str, MemoryEdge],
            outcome: _MutationOutcome,
        ) -> None:
            calls.append((older.memory_id, newer.memory_id))
            super()._repair_pair(
                older=older,
                newer=newer,
                at=at,
                graph_store=graph_store,
                memory_store=memory_store,
                existing_edges=existing_edges,
                outcome=outcome,
            )

    strategy = _CapturingContradictionStrategy()
    first = _memory("first", "Atlas plan has 1 stage", topic="atlas", observed_at=now)
    second = _memory(
        "second",
        "Atlas plan has 2 stage",
        topic="atlas",
        observed_at=now,
    )
    third = _memory("third", "Atlas plan has 3 stage", topic="atlas", observed_at=now)
    strategy._repair_topic_members(
        members=[first, second, third],
        at=now,
        graph_store=InMemoryGraphStore((first, second, third)),
        memory_store=InMemoryMemoryStore((first, second, third)),
        existing_edges={},
        outcome=_MutationOutcome.empty(),
    )

    assert calls == [("first", "second"), ("first", "third"), ("second", "third")]


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
