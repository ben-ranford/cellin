"""Deterministic scheduling for Cellin dream runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cellin.core import GraphStore, MemoryStore, ScheduledDreamRun


@dataclass(slots=True)
class DeterministicDreamScheduler:
    """Schedules dream strategies from memory pressure and graph signals."""

    memory_store: MemoryStore
    graph_store: GraphStore
    cadence_hours: int = 24
    minimum_memory_count: int = 4
    last_run_at: dict[str, datetime] = field(default_factory=dict)

    def plan(self, now: datetime) -> tuple[ScheduledDreamRun, ...]:
        active_memories = tuple(self.memory_store.list_by(archived=False))
        active_edges = self.graph_store.list_edges()
        runs: list[ScheduledDreamRun] = []

        if len(active_memories) >= self.minimum_memory_count and self._due("deduplication", now):
            runs.append(
                ScheduledDreamRun(
                    strategy_name="deduplication",
                    scheduled_for=now,
                    reason=f"memory-pressure:{len(active_memories)}",
                )
            )

        contradiction_count = sum(1 for edge in active_edges if edge.kind.value == "contradicts")
        if contradiction_count > 0 and self._due("contradiction_repair", now):
            runs.append(
                ScheduledDreamRun(
                    strategy_name="contradiction_repair",
                    scheduled_for=now,
                    reason=f"contradictions:{contradiction_count}",
                )
            )

        topics = Counter(
            str(topic)
            for topic in (memory.metadata.get("topic") for memory in active_memories)
            if isinstance(topic, str)
        )
        summarizable_topics = sum(1 for count in topics.values() if count >= 2)
        if summarizable_topics > 0 and self._due("abstraction", now):
            runs.append(
                ScheduledDreamRun(
                    strategy_name="abstraction",
                    scheduled_for=now,
                    reason=f"summarizable-topics:{summarizable_topics}",
                )
            )

        decay_candidates = [
            memory
            for memory in active_memories
            if memory.decay.half_life_days is not None
            and (now - (memory.observed_at or memory.created_at)).days > memory.decay.half_life_days
        ]
        if decay_candidates and self._due("decay_archival", now):
            runs.append(
                ScheduledDreamRun(
                    strategy_name="decay_archival",
                    scheduled_for=now,
                    reason=f"decay-candidates:{len(decay_candidates)}",
                )
            )

        return tuple(runs)

    def record_run(self, strategy_name: str, when: datetime) -> None:
        self.last_run_at[strategy_name] = when

    def _due(self, strategy_name: str, now: datetime) -> bool:
        last = self.last_run_at.get(strategy_name)
        if last is None:
            return True
        return now - last >= timedelta(hours=self.cadence_hours)
