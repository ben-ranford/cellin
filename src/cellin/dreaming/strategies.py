"""Deterministic dream strategies for Cellin's local-first MVP."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

from cellin.core import (
    DreamArtifact,
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
)
from cellin.core.models import JSONValue
from cellin.dreaming.models import DreamDiff, DreamEdgeChange, DreamMemoryChange, DreamRunResult

TOKEN_RE = re.compile(r"[a-z0-9]+")
NEGATION_MARKERS = {
    "cancelled",
    "canceled",
    "blocked",
    "failed",
    "rolled",
    "rollback",
    "removed",
    "not",
}
SUCCESS_MARKERS = {"completed", "green", "released", "shipped", "stable", "active", "enabled"}


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _similarity(left: MemoryAtom, right: MemoryAtom) -> float:
    left_tokens = _tokenize(left.text)
    right_tokens = _tokenize(right.text)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _contains_conflict(left: MemoryAtom, right: MemoryAtom) -> bool:
    left_tokens = _tokenize(left.text)
    right_tokens = _tokenize(right.text)
    left_negative = bool(left_tokens & NEGATION_MARKERS)
    right_negative = bool(right_tokens & NEGATION_MARKERS)
    left_positive = bool(left_tokens & SUCCESS_MARKERS)
    right_positive = bool(right_tokens & SUCCESS_MARKERS)
    if left_negative != right_negative and (left_positive or right_positive):
        return True

    left_numbers = {token for token in left_tokens if token.isdigit()}
    right_numbers = {token for token in right_tokens if token.isdigit()}
    return bool(left_numbers and right_numbers and left_numbers != right_numbers)


def _active_edges(graph_store: GraphStore) -> dict[str, MemoryEdge]:
    return {edge.edge_id: edge for edge in graph_store.list_edges()}


def _best_memory(memories: tuple[MemoryAtom, ...]) -> MemoryAtom:
    return max(
        memories,
        key=lambda memory: (
            memory.trust_score,
            memory.salience_score,
            memory.retrieval.access_count,
            memory.observed_at or memory.created_at,
        ),
    )


def _summary_text(topic: str, members: tuple[MemoryAtom, ...]) -> str:
    snippets = []
    for memory in members:
        cleaned = memory.text.strip().rstrip(".")
        if cleaned and cleaned not in snippets:
            snippets.append(cleaned)
        if len(snippets) == 3:
            break
    body = "; ".join(snippets)
    return f"{topic.title()} memory summary: {body}."


def _string_list(value: JSONValue) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _group_active_memories_by_topic(memory_store: MemoryStore) -> dict[str, list[MemoryAtom]]:
    topic_groups: dict[str, list[MemoryAtom]] = defaultdict(list)
    for memory in memory_store.list():
        if memory.decay.archived:
            continue
        topic = memory.metadata.get("topic")
        if isinstance(topic, str):
            topic_groups[topic].append(memory)
    return topic_groups


def _serialize_pairs(pairs: list[tuple[str, str]]) -> list[JSONValue]:
    return [cast(JSONValue, [left_id, right_id]) for left_id, right_id in pairs]


def _build_pair_run_result(
    *,
    strategy_name: str,
    at: datetime,
    pairs: list[tuple[str, str]],
    pair_key: str,
    summary: str,
    memory_changes: list[DreamMemoryChange],
    edge_changes: list[DreamEdgeChange],
) -> DreamRunResult:
    run_id = f"{strategy_name}:{at.isoformat()}"
    serialized_pairs = _serialize_pairs(pairs)
    artifact = DreamArtifact(
        dream_id=run_id,
        strategy_name=strategy_name,
        provenance=Provenance(source_id=run_id, source_type="dream"),
        created_at=at,
        summary=summary,
        affected_memory_ids=tuple(memory_id for pair in pairs for memory_id in pair),
        metadata={pair_key: serialized_pairs},
    )
    diff = DreamDiff(
        run_id=run_id,
        strategy_name=strategy_name,
        created_at=at,
        memory_changes=tuple(memory_changes),
        edge_changes=tuple(edge_changes),
        notes={pair_key: serialized_pairs},
    )
    return DreamRunResult(artifact=artifact, diff=diff)


def _apply_memory_updates(
    *,
    graph_store: GraphStore,
    memory_store: MemoryStore,
    before_after: tuple[tuple[MemoryAtom, MemoryAtom], ...],
) -> list[DreamMemoryChange]:
    changes: list[DreamMemoryChange] = []
    for before, after in before_after:
        memory_store.put(after)
        graph_store.upsert_memory(after)
        changes.append(DreamMemoryChange(before.memory_id, before, after))
    return changes


@dataclass(slots=True)
class _MutationOutcome:
    memory_changes: list[DreamMemoryChange]
    edge_changes: list[DreamEdgeChange]
    pairs: list[tuple[str, str]]

    @classmethod
    def empty(cls) -> _MutationOutcome:
        return cls(memory_changes=[], edge_changes=[], pairs=[])


@dataclass(slots=True)
class DeduplicationDreamStrategy:
    """Archives near-identical memories and links them to a canonical node."""

    strategy_name: str = "deduplication"
    similarity_threshold: float = 0.92

    def execute(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        *,
        at: datetime | None = None,
    ) -> DreamRunResult | None:
        when = at or datetime.now(UTC)
        outcome = _MutationOutcome.empty()
        for members in _group_active_memories_by_topic(memory_store).values():
            self._merge_topic_members(
                members=members,
                at=when,
                graph_store=graph_store,
                memory_store=memory_store,
                outcome=outcome,
            )

        if not outcome.pairs:
            return None

        return _build_pair_run_result(
            strategy_name=self.strategy_name,
            at=when,
            pairs=outcome.pairs,
            pair_key="merged_pairs",
            summary=f"Archived {len(outcome.pairs)} duplicate memories.",
            memory_changes=outcome.memory_changes,
            edge_changes=outcome.edge_changes,
        )

    def _merge_topic_members(
        self,
        *,
        members: list[MemoryAtom],
        at: datetime,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        outcome: _MutationOutcome,
    ) -> None:
        if len(members) < 2:
            return

        for index, left in enumerate(members[:-1]):
            for right in members[index + 1 :]:
                self._merge_pair(
                    left=left,
                    right=right,
                    at=at,
                    graph_store=graph_store,
                    memory_store=memory_store,
                    outcome=outcome,
                )

    def _merge_pair(
        self,
        *,
        left: MemoryAtom,
        right: MemoryAtom,
        at: datetime,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        outcome: _MutationOutcome,
    ) -> None:
        if not self._is_merge_candidate(left=left, right=right):
            return

        canonical, duplicate = self._canonical_duplicate_pair(left=left, right=right)
        if duplicate.decay.archived:
            return

        outcome.pairs.append((duplicate.memory_id, canonical.memory_id))
        canonical_after, duplicate_after = self._updated_dedup_memories(
            canonical=canonical,
            duplicate=duplicate,
            at=at,
        )
        edge_after = self._same_as_edge(duplicate=duplicate, canonical=canonical, at=at)
        changes = _apply_memory_updates(
            graph_store=graph_store,
            memory_store=memory_store,
            before_after=((canonical, canonical_after), (duplicate, duplicate_after)),
        )
        graph_store.upsert_edge(edge_after)
        outcome.memory_changes.extend(changes)
        outcome.edge_changes.append(DreamEdgeChange(edge_after.edge_id, None, edge_after))

    def _is_merge_candidate(self, *, left: MemoryAtom, right: MemoryAtom) -> bool:
        if _contains_conflict(left, right):
            return False
        return _similarity(left, right) >= self.similarity_threshold

    def _canonical_duplicate_pair(
        self,
        *,
        left: MemoryAtom,
        right: MemoryAtom,
    ) -> tuple[MemoryAtom, MemoryAtom]:
        canonical = _best_memory((left, right))
        duplicate = right if canonical.memory_id == left.memory_id else left
        return canonical, duplicate

    def _updated_dedup_memories(
        self,
        *,
        canonical: MemoryAtom,
        duplicate: MemoryAtom,
        at: datetime,
    ) -> tuple[MemoryAtom, MemoryAtom]:
        deduplicated_ids: list[JSONValue] = [
            memory_id
            for memory_id in sorted(
                {
                    *_string_list(canonical.metadata.get("deduplicated_memory_ids")),
                    duplicate.memory_id,
                }
            )
        ]
        canonical_after = replace(
            canonical,
            salience_score=min(1.0, canonical.salience_score + 0.05),
            retrieval=replace(
                canonical.retrieval,
                access_count=canonical.retrieval.access_count + duplicate.retrieval.access_count,
            ),
            decay=replace(canonical.decay, last_reinforced_at=at),
            metadata={
                **canonical.metadata,
                "deduplicated_memory_ids": deduplicated_ids,
            },
        )
        duplicate_after = replace(
            duplicate,
            decay=replace(duplicate.decay, archived=True, last_reinforced_at=at),
            metadata={**duplicate.metadata, "canonical_memory_id": canonical.memory_id},
        )
        return canonical_after, duplicate_after

    def _same_as_edge(
        self,
        *,
        duplicate: MemoryAtom,
        canonical: MemoryAtom,
        at: datetime,
    ) -> MemoryEdge:
        return MemoryEdge(
            edge_id=f"same-as:{duplicate.memory_id}:{canonical.memory_id}",
            source_id=duplicate.memory_id,
            target_id=canonical.memory_id,
            kind=EdgeKind.SAME_AS,
            provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
            created_at=at,
            metadata={"dream_run": self.strategy_name},
        )


@dataclass(slots=True)
class ContradictionRepairDreamStrategy:
    """Links contradictory memories and down-ranks stale claims."""

    strategy_name: str = "contradiction_repair"

    def execute(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        *,
        at: datetime | None = None,
    ) -> DreamRunResult | None:
        when = at or datetime.now(UTC)
        existing_edges = _active_edges(graph_store)
        outcome = _MutationOutcome.empty()
        for members in _group_active_memories_by_topic(memory_store).values():
            self._repair_topic_members(
                members=members,
                at=when,
                graph_store=graph_store,
                memory_store=memory_store,
                existing_edges=existing_edges,
                outcome=outcome,
            )

        if not outcome.pairs:
            return None

        return _build_pair_run_result(
            strategy_name=self.strategy_name,
            at=when,
            pairs=outcome.pairs,
            pair_key="repaired_pairs",
            summary=f"Linked {len(outcome.pairs)} contradictory memory pairs.",
            memory_changes=outcome.memory_changes,
            edge_changes=outcome.edge_changes,
        )

    def _repair_topic_members(
        self,
        *,
        members: list[MemoryAtom],
        at: datetime,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        existing_edges: dict[str, MemoryEdge],
        outcome: _MutationOutcome,
    ) -> None:
        ordered = sorted(members, key=lambda memory: memory.observed_at or memory.created_at)
        for older in ordered[:-1]:
            for newer in ordered[1:]:
                self._repair_pair(
                    older=older,
                    newer=newer,
                    at=at,
                    graph_store=graph_store,
                    memory_store=memory_store,
                    existing_edges=existing_edges,
                    outcome=outcome,
                )

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
        if not _contains_conflict(older, newer):
            return

        edge_id = self._contradiction_edge_id(older=older, newer=newer)
        if edge_id in existing_edges:
            return

        older_after, newer_after = self._updated_contradiction_memories(
            older=older,
            newer=newer,
        )
        edge_after = self._contradiction_edge(
            edge_id=edge_id,
            older=older,
            newer=newer,
            at=at,
        )
        changes = _apply_memory_updates(
            graph_store=graph_store,
            memory_store=memory_store,
            before_after=((older, older_after), (newer, newer_after)),
        )
        graph_store.upsert_edge(edge_after)
        existing_edges[edge_id] = edge_after

        outcome.pairs.append((older.memory_id, newer.memory_id))
        outcome.memory_changes.extend(changes)
        outcome.edge_changes.append(DreamEdgeChange(edge_id, None, edge_after))

    def _contradiction_edge_id(self, *, older: MemoryAtom, newer: MemoryAtom) -> str:
        return f"contradicts:{older.memory_id}:{newer.memory_id}"

    def _updated_contradiction_memories(
        self,
        *,
        older: MemoryAtom,
        newer: MemoryAtom,
    ) -> tuple[MemoryAtom, MemoryAtom]:
        older_after = replace(
            older,
            trust_score=max(0.1, round(older.trust_score - 0.25, 6)),
            metadata={**older.metadata, "superseded_by": newer.memory_id},
        )
        newer_after = replace(
            newer,
            salience_score=min(1.0, round(newer.salience_score + 0.1, 6)),
            metadata={**newer.metadata, "contradicts": older.memory_id},
        )
        return older_after, newer_after

    def _contradiction_edge(
        self,
        *,
        edge_id: str,
        older: MemoryAtom,
        newer: MemoryAtom,
        at: datetime,
    ) -> MemoryEdge:
        return MemoryEdge(
            edge_id=edge_id,
            source_id=older.memory_id,
            target_id=newer.memory_id,
            kind=EdgeKind.CONTRADICTS,
            provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
            created_at=at,
            metadata={"dream_run": self.strategy_name},
        )


@dataclass(slots=True)
class AbstractionDreamStrategy:
    """Builds deterministic summary memories over a topic cluster."""

    strategy_name: str = "abstraction"

    def execute(
        self,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        *,
        at: datetime | None = None,
    ) -> DreamRunResult | None:
        when = at or datetime.now(UTC)
        topic_groups: dict[str, list[MemoryAtom]] = defaultdict(list)
        active_memories = tuple(
            memory for memory in memory_store.list() if not memory.decay.archived
        )
        for memory in active_memories:
            topic = memory.metadata.get("topic")
            if isinstance(topic, str) and memory.kind != MemoryKind.DREAM:
                topic_groups[topic].append(memory)

        existing_summaries = {
            memory.metadata.get("topic")
            for memory in active_memories
            if memory.kind == MemoryKind.DREAM and isinstance(memory.metadata.get("topic"), str)
        }

        memory_changes: list[DreamMemoryChange] = []
        edge_changes: list[DreamEdgeChange] = []
        created_ids: list[str] = []

        for topic, members in topic_groups.items():
            if len(members) < 2 or topic in existing_summaries:
                continue

            ordered_members = tuple(
                sorted(members, key=lambda item: item.salience_score, reverse=True)
            )
            summary_text = _summary_text(topic, ordered_members)
            summary_memory = MemoryAtom(
                memory_id=f"dream-{topic}-{when.strftime('%Y%m%d%H%M%S')}",
                kind=MemoryKind.DREAM,
                text=summary_text,
                provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
                modality=Modality.TEXT,
                created_at=when,
                observed_at=when,
                salience_score=min(1.0, max(memory.salience_score for memory in members) + 0.05),
                trust_score=min(memory.trust_score for memory in members),
                metadata={
                    "topic": topic,
                    "dream_strategy": self.strategy_name,
                    "summary_for": [memory.memory_id for memory in members],
                    "token_count": len(summary_text.split()),
                },
            )
            memory_store.put(summary_memory)
            graph_store.upsert_memory(summary_memory)
            memory_changes.append(DreamMemoryChange(summary_memory.memory_id, None, summary_memory))
            created_ids.append(summary_memory.memory_id)

            for member in members:
                edge_after = MemoryEdge(
                    edge_id=f"summarizes:{summary_memory.memory_id}:{member.memory_id}",
                    source_id=summary_memory.memory_id,
                    target_id=member.memory_id,
                    kind=EdgeKind.SUMMARIZES,
                    provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
                    created_at=when,
                    metadata={"topic": topic},
                )
                graph_store.upsert_edge(edge_after)
                edge_changes.append(DreamEdgeChange(edge_after.edge_id, None, edge_after))

        if not created_ids:
            return None

        run_id = f"{self.strategy_name}:{when.isoformat()}"
        artifact = DreamArtifact(
            dream_id=run_id,
            strategy_name=self.strategy_name,
            provenance=Provenance(source_id=run_id, source_type="dream"),
            created_at=when,
            summary=f"Created {len(created_ids)} summary memories.",
            affected_memory_ids=tuple(created_ids),
            metadata={"created_memory_ids": [memory_id for memory_id in created_ids]},
        )
        diff = DreamDiff(
            run_id=run_id,
            strategy_name=self.strategy_name,
            created_at=when,
            memory_changes=tuple(memory_changes),
            edge_changes=tuple(edge_changes),
            notes={"created_memory_ids": [memory_id for memory_id in created_ids]},
        )
        return DreamRunResult(artifact=artifact, diff=diff)
