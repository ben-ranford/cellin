"""Additional dream scheduler and runner coverage."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cellin.core import (
    DecayState,
    DreamArtifact,
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
    RetrievalStats,
    ScheduledDreamRun,
)
from cellin.dreaming.models import DreamDiff, DreamEdgeChange, DreamMemoryChange, DreamRunResult
from cellin.dreaming.scheduler import DeterministicDreamScheduler
from cellin.dreaming.service import DreamRunner
from cellin.stores._store_utils import filter_memories


def _memory(
    memory_id: str,
    text: str,
    *,
    observed_at: datetime,
    topic: str,
    archived: bool = False,
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
        trust_score=0.9,
        decay=DecayState(archived=archived, half_life_days=14.0),
        retrieval=RetrievalStats(),
        metadata={"topic": topic},
    )


def _edge(edge_id: str, source_id: str, target_id: str, *, kind: EdgeKind) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
    )


@dataclass
class InMemoryMemoryStore(MemoryStore):
    memories: dict[str, MemoryAtom]

    def __init__(self, memories: tuple[MemoryAtom, ...]) -> None:
        self.memories = {memory.memory_id: memory for memory in memories}

    def put(self, memory: MemoryAtom) -> None:
        self.memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self.memories.values())

    def list_by(
        self,
        *,
        archived: bool | None = None,
        topic: str | None = None,
    ) -> Sequence[MemoryAtom]:
        return filter_memories(self.memories.values(), archived=archived, topic=topic)


@dataclass
class InMemoryGraphStore(GraphStore):
    memories: dict[str, MemoryAtom]
    edges: dict[str, MemoryEdge]

    def __init__(
        self,
        memories: tuple[MemoryAtom, ...],
        edges: tuple[MemoryEdge, ...] = (),
    ) -> None:
        self.memories = {memory.memory_id: memory for memory in memories}
        self.edges = {edge.edge_id: edge for edge in edges}

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self.memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.edges[edge.edge_id] = edge

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self.edges.values()
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self.edges.values())


@dataclass
class StubScheduler:
    planned_runs: tuple[ScheduledDreamRun, ...]
    recorded_runs: list[tuple[str, datetime]]

    def plan(self, _: datetime) -> tuple[ScheduledDreamRun, ...]:
        return self.planned_runs

    def record_run(self, strategy_name: str, when: datetime) -> None:
        self.recorded_runs.append((strategy_name, when))


@dataclass
class StubStrategy:
    result: DreamRunResult | None
    observed_at: datetime | None = None

    def execute(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        *,
        at: datetime | None = None,
    ) -> DreamRunResult | None:
        assert graph_store is not None
        assert memory_store is not None
        self.observed_at = at
        return self.result


def test_scheduler_plans_due_runs_and_respects_cadence() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    memories = (
        _memory("atlas-1", "Atlas planning note", observed_at=now, topic="atlas"),
        _memory("atlas-2", "Atlas rollout note", observed_at=now, topic="atlas"),
        _memory("atlas-3", "Atlas support note", observed_at=now, topic="atlas"),
        _memory("ops-1", "Ops note", observed_at=now, topic="ops"),
    )
    edges = (_edge("contradiction", "atlas-1", "atlas-2", kind=EdgeKind.CONTRADICTS),)
    scheduler = DeterministicDreamScheduler(
        memory_store=InMemoryMemoryStore(memories),
        graph_store=InMemoryGraphStore(memories, edges),
    )

    initial = scheduler.plan(now)

    assert {run.strategy_name for run in initial} == {
        "deduplication",
        "contradiction_repair",
        "abstraction",
    }
    scheduler.record_run("deduplication", now)
    scheduler.record_run("contradiction_repair", now)
    scheduler.record_run("abstraction", now)
    assert scheduler.plan(now + timedelta(hours=1)) == ()
    assert len(scheduler.plan(now + timedelta(hours=24))) == 3


def test_dream_runner_run_pending_and_rollback_cover_all_diff_paths() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    original_memory = _memory("atlas-1", "Atlas memory", observed_at=now, topic="atlas")
    updated_memory = _memory("atlas-1", "Atlas memory updated", observed_at=now, topic="atlas")
    created_memory = _memory("atlas-new", "New memory", observed_at=now, topic="atlas")
    original_edge = _edge("supports:before", "atlas-1", "atlas-2", kind=EdgeKind.SUPPORTS)
    updated_edge = _edge("supports:before", "atlas-1", "atlas-3", kind=EdgeKind.SUPPORTS)
    created_edge = _edge("supports:new", "atlas-new", "atlas-1", kind=EdgeKind.SUPPORTS)
    diff = DreamDiff(
        run_id="dream-run",
        strategy_name="deduplication",
        created_at=now,
        memory_changes=(
            DreamMemoryChange(original_memory.memory_id, original_memory, updated_memory),
            DreamMemoryChange(created_memory.memory_id, None, created_memory),
        ),
        edge_changes=(
            DreamEdgeChange(original_edge.edge_id, original_edge, updated_edge),
            DreamEdgeChange(created_edge.edge_id, None, created_edge),
        ),
    )
    result = DreamRunResult(
        artifact=DreamArtifact(
            dream_id="dream-run",
            strategy_name="deduplication",
            provenance=Provenance(source_id="dream-run", source_type="dream"),
            created_at=now,
            summary="Dreamed",
            affected_memory_ids=(original_memory.memory_id, created_memory.memory_id),
        ),
        diff=diff,
    )
    scheduler = StubScheduler(
        planned_runs=(
            ScheduledDreamRun("apply", now, "scheduled"),
            ScheduledDreamRun("noop", now, "scheduled"),
        ),
        recorded_runs=[],
    )
    apply_strategy = StubStrategy(result)
    noop_strategy = StubStrategy(None)
    memory_store = InMemoryMemoryStore((original_memory,))
    graph_store = InMemoryGraphStore((original_memory,), (original_edge,))
    runner = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        scheduler=scheduler,  # type: ignore[arg-type]
        strategies={"apply": apply_strategy, "noop": noop_strategy},
    )

    pending = runner.run_pending(now=now)

    assert pending == (result,)
    assert scheduler.recorded_runs == [("apply", now)]
    assert apply_strategy.observed_at == now
    assert noop_strategy.observed_at == now

    runner.rollback(diff)

    rolled_back_created = memory_store.get(created_memory.memory_id)
    assert rolled_back_created is not None
    assert rolled_back_created.decay.archived is True
    assert memory_store.get(original_memory.memory_id) == original_memory
    assert graph_store.edges[created_edge.edge_id].metadata["archived"] is True
    assert graph_store.edges[original_edge.edge_id] == original_edge


def test_scheduler_plans_decay_archival_for_expired_memories() -> None:
    from datetime import timedelta

    now = datetime(2026, 4, 5, tzinfo=UTC)
    old_date = now - timedelta(days=20)

    expired = _memory("expired", "Old memory", observed_at=old_date, topic="atlas")
    fresh = _memory("fresh", "Fresh memory", observed_at=now, topic="atlas")
    scheduler = DeterministicDreamScheduler(
        memory_store=InMemoryMemoryStore((expired, fresh)),
        graph_store=InMemoryGraphStore((expired, fresh)),
    )

    runs = scheduler.plan(now)
    assert any(run.strategy_name == "decay_archival" for run in runs)
    decay_run = next(r for r in runs if r.strategy_name == "decay_archival")
    assert "decay-candidates:1" in decay_run.reason


def test_dream_runner_deletes_from_vector_store_on_archive() -> None:
    from cellin.stores import InMemoryVectorIndex

    now = datetime(2026, 4, 5, tzinfo=UTC)
    original = _memory("atlas-1", "Atlas memory", observed_at=now, topic="atlas")
    archived_version = _memory("atlas-1", "Atlas memory", observed_at=now, topic="atlas")

    from dataclasses import replace as dc_replace

    archived_version = dc_replace(
        archived_version, decay=DecayState(archived=True, half_life_days=14.0)
    )

    diff = DreamDiff(
        run_id="dream-run",
        strategy_name="decay_archival",
        created_at=now,
        memory_changes=(DreamMemoryChange(original.memory_id, original, archived_version),),
        edge_changes=(),
    )
    result = DreamRunResult(
        artifact=DreamArtifact(
            dream_id="dream-run",
            strategy_name="decay_archival",
            provenance=Provenance(source_id="dream-run", source_type="dream"),
            created_at=now,
            summary="Archived 1 decayed memories.",
            affected_memory_ids=(original.memory_id,),
        ),
        diff=diff,
    )
    scheduler = StubScheduler(
        planned_runs=(ScheduledDreamRun("decay_archival", now, "decay-candidates:1"),),
        recorded_runs=[],
    )
    apply_strategy = StubStrategy(result)
    memory_store = InMemoryMemoryStore((original,))
    graph_store = InMemoryGraphStore((original,))
    vector_store = InMemoryVectorIndex()
    vector_store.upsert(original.memory_id, original.text)

    runner = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        scheduler=scheduler,  # type: ignore[arg-type]
        strategies={"decay_archival": apply_strategy},
        vector_store=vector_store,
    )

    runner.run_pending(now=now)

    # Vector entry should have been deleted for the archived memory
    results = vector_store.search("Atlas memory", limit=5)
    assert not any(r.memory_id == original.memory_id for r in results)

    # Rollback should re-upsert vector
    runner.rollback(diff)
    results_after_rollback = vector_store.search("Atlas memory", limit=5)
    assert any(r.memory_id == original.memory_id for r in results_after_rollback)
