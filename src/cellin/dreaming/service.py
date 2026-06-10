"""Dream execution and rollback orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from cellin.core import GraphStore, MemoryAtom, MemoryEdge, MemoryStore, VectorStore
from cellin.dreaming.models import DreamDiff, DreamEdgeChange, DreamMemoryChange, DreamRunResult
from cellin.dreaming.scheduler import DeterministicDreamScheduler
from cellin.dreaming.strategies import (
    AbstractionDreamStrategy,
    ContradictionRepairDreamStrategy,
    DecayArchivalDreamStrategy,
    DeduplicationDreamStrategy,
)


class DreamExecutable(Protocol):
    def execute(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        *,
        at: datetime | None = None,
    ) -> DreamRunResult | None:
        """Execute a deterministic dream strategy."""


class DreamRunner:
    """Runs deterministic dream strategies and can roll them back."""

    def __init__(
        self,
        *,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        scheduler: DeterministicDreamScheduler | None = None,
        strategies: Mapping[str, DreamExecutable] | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.graph_store = graph_store
        self.memory_store = memory_store
        self.vector_store = vector_store
        self.scheduler = scheduler or DeterministicDreamScheduler(memory_store, graph_store)
        self.strategies = strategies or {
            "deduplication": DeduplicationDreamStrategy(),
            "contradiction_repair": ContradictionRepairDreamStrategy(),
            "abstraction": AbstractionDreamStrategy(),
            "decay_archival": DecayArchivalDreamStrategy(),
        }

    def run_strategy(
        self, strategy_name: str, *, at: datetime | None = None
    ) -> DreamRunResult | None:
        strategy = self.strategies[strategy_name]
        when = at or datetime.now(UTC)
        result = strategy.execute(self.graph_store, self.memory_store, at=when)
        if result is not None:
            self.scheduler.record_run(strategy_name, when)
            if self.vector_store is not None and hasattr(self.vector_store, "delete"):
                for change in result.diff.memory_changes:
                    after = change.after
                    before = change.before
                    if (
                        after is not None
                        and after.decay.archived
                        and (before is None or not before.decay.archived)
                    ):
                        self.vector_store.delete(after.memory_id)
        return result

    def run_pending(self, *, now: datetime | None = None) -> tuple[DreamRunResult, ...]:
        when = now or datetime.now(UTC)
        results: list[DreamRunResult] = []
        for scheduled in self.scheduler.plan(when):
            result = self.run_strategy(scheduled.strategy_name, at=scheduled.scheduled_for)
            if result is not None:
                results.append(result)
        return tuple(results)

    def _archive_edge(self, edge: MemoryEdge) -> None:
        self.graph_store.upsert_edge(
            replace(
                edge,
                metadata={**edge.metadata, "archived": True},
            )
        )

    def _rollback_edge_change(self, edge_change: DreamEdgeChange) -> None:
        if edge_change.before is None and edge_change.after is not None:
            self._archive_edge(edge_change.after)
        elif edge_change.before is not None:
            self.graph_store.upsert_edge(edge_change.before)

    def _archive_memory(self, memory: MemoryAtom) -> None:
        archived = replace(
            memory,
            decay=replace(memory.decay, archived=True),
        )
        self.memory_store.put(archived)
        self.graph_store.upsert_memory(archived)

    def _restore_vector_if_needed(self, restored: MemoryAtom, after: MemoryAtom | None) -> None:
        if self.vector_store is None or not hasattr(self.vector_store, "delete"):
            return
        if after is not None and after.decay.archived and not restored.decay.archived:
            self.vector_store.upsert(restored.memory_id, restored.text)

    def _rollback_memory_change(self, memory_change: DreamMemoryChange) -> None:
        if memory_change.before is None and memory_change.after is not None:
            self._archive_memory(memory_change.after)
        elif memory_change.before is not None:
            restored = memory_change.before
            self.memory_store.put(restored)
            self.graph_store.upsert_memory(restored)
            self._restore_vector_if_needed(restored, memory_change.after)

    def rollback(self, diff: DreamDiff) -> None:
        for edge_change in reversed(diff.edge_changes):
            self._rollback_edge_change(edge_change)

        for memory_change in reversed(diff.memory_changes):
            self._rollback_memory_change(memory_change)
