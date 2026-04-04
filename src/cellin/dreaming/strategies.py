"""Deterministic dream strategies for Cellin's local-first MVP."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime

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
        topic_groups: dict[str, list[MemoryAtom]] = defaultdict(list)
        for memory in memory_store.list():
            if memory.decay.archived:
                continue
            topic = memory.metadata.get("topic")
            if isinstance(topic, str):
                topic_groups[topic].append(memory)

        memory_changes: list[DreamMemoryChange] = []
        edge_changes: list[DreamEdgeChange] = []
        merged_pairs: list[tuple[str, str]] = []

        for _topic, members in topic_groups.items():
            if len(members) < 2:
                continue

            for index, left in enumerate(members[:-1]):
                for right in members[index + 1 :]:
                    if _contains_conflict(left, right):
                        continue
                    if _similarity(left, right) < self.similarity_threshold:
                        continue

                    canonical = _best_memory((left, right))
                    duplicate = right if canonical.memory_id == left.memory_id else left
                    if duplicate.decay.archived:
                        continue

                    merged_pairs.append((duplicate.memory_id, canonical.memory_id))

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
                            access_count=canonical.retrieval.access_count
                            + duplicate.retrieval.access_count,
                        ),
                        decay=replace(canonical.decay, last_reinforced_at=when),
                        metadata={
                            **canonical.metadata,
                            "deduplicated_memory_ids": deduplicated_ids,
                        },
                    )
                    duplicate_after = replace(
                        duplicate,
                        decay=replace(duplicate.decay, archived=True, last_reinforced_at=when),
                        metadata={**duplicate.metadata, "canonical_memory_id": canonical.memory_id},
                    )
                    edge_after = MemoryEdge(
                        edge_id=f"same-as:{duplicate.memory_id}:{canonical.memory_id}",
                        source_id=duplicate.memory_id,
                        target_id=canonical.memory_id,
                        kind=EdgeKind.SAME_AS,
                        provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
                        created_at=when,
                        metadata={"dream_run": self.strategy_name},
                    )

                    memory_store.put(canonical_after)
                    graph_store.upsert_memory(canonical_after)
                    memory_store.put(duplicate_after)
                    graph_store.upsert_memory(duplicate_after)
                    graph_store.upsert_edge(edge_after)

                    memory_changes.extend(
                        (
                            DreamMemoryChange(canonical.memory_id, canonical, canonical_after),
                            DreamMemoryChange(duplicate.memory_id, duplicate, duplicate_after),
                        )
                    )
                    edge_changes.append(DreamEdgeChange(edge_after.edge_id, None, edge_after))

        if not merged_pairs:
            return None

        run_id = f"{self.strategy_name}:{when.isoformat()}"
        artifact = DreamArtifact(
            dream_id=run_id,
            strategy_name=self.strategy_name,
            provenance=Provenance(source_id=run_id, source_type="dream"),
            created_at=when,
            summary=f"Archived {len(merged_pairs)} duplicate memories.",
            affected_memory_ids=tuple(memory_id for pair in merged_pairs for memory_id in pair),
            metadata={"merged_pairs": [list(pair) for pair in merged_pairs]},
        )
        diff = DreamDiff(
            run_id=run_id,
            strategy_name=self.strategy_name,
            created_at=when,
            memory_changes=tuple(memory_changes),
            edge_changes=tuple(edge_changes),
            notes={"merged_pairs": [list(pair) for pair in merged_pairs]},
        )
        return DreamRunResult(artifact=artifact, diff=diff)


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
        topic_groups: dict[str, list[MemoryAtom]] = defaultdict(list)
        for memory in memory_store.list():
            if memory.decay.archived:
                continue
            topic = memory.metadata.get("topic")
            if isinstance(topic, str):
                topic_groups[topic].append(memory)

        existing_edges = _active_edges(graph_store)
        memory_changes: list[DreamMemoryChange] = []
        edge_changes: list[DreamEdgeChange] = []
        repaired_pairs: list[tuple[str, str]] = []

        for members in topic_groups.values():
            ordered = sorted(members, key=lambda memory: memory.observed_at or memory.created_at)
            for older in ordered[:-1]:
                for newer in ordered[1:]:
                    if not _contains_conflict(older, newer):
                        continue

                    edge_id = f"contradicts:{older.memory_id}:{newer.memory_id}"
                    if edge_id in existing_edges:
                        continue

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
                    edge_after = MemoryEdge(
                        edge_id=edge_id,
                        source_id=older.memory_id,
                        target_id=newer.memory_id,
                        kind=EdgeKind.CONTRADICTS,
                        provenance=Provenance(source_id=self.strategy_name, source_type="dream"),
                        created_at=when,
                        metadata={"dream_run": self.strategy_name},
                    )

                    memory_store.put(older_after)
                    graph_store.upsert_memory(older_after)
                    memory_store.put(newer_after)
                    graph_store.upsert_memory(newer_after)
                    graph_store.upsert_edge(edge_after)
                    existing_edges[edge_id] = edge_after

                    repaired_pairs.append((older.memory_id, newer.memory_id))
                    memory_changes.extend(
                        (
                            DreamMemoryChange(older.memory_id, older, older_after),
                            DreamMemoryChange(newer.memory_id, newer, newer_after),
                        )
                    )
                    edge_changes.append(DreamEdgeChange(edge_id, None, edge_after))

        if not repaired_pairs:
            return None

        run_id = f"{self.strategy_name}:{when.isoformat()}"
        artifact = DreamArtifact(
            dream_id=run_id,
            strategy_name=self.strategy_name,
            provenance=Provenance(source_id=run_id, source_type="dream"),
            created_at=when,
            summary=f"Linked {len(repaired_pairs)} contradictory memory pairs.",
            affected_memory_ids=tuple(memory_id for pair in repaired_pairs for memory_id in pair),
            metadata={"repaired_pairs": [list(pair) for pair in repaired_pairs]},
        )
        diff = DreamDiff(
            run_id=run_id,
            strategy_name=self.strategy_name,
            created_at=when,
            memory_changes=tuple(memory_changes),
            edge_changes=tuple(edge_changes),
            notes={"repaired_pairs": [list(pair) for pair in repaired_pairs]},
        )
        return DreamRunResult(artifact=artifact, diff=diff)


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

            summary_memory = MemoryAtom(
                memory_id=f"dream-{topic}-{when.strftime('%Y%m%d%H%M%S')}",
                kind=MemoryKind.DREAM,
                text=_summary_text(
                    topic,
                    tuple(sorted(members, key=lambda item: item.salience_score, reverse=True)),
                ),
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
                    "token_count": len(_summary_text(topic, tuple(members)).split()),
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
