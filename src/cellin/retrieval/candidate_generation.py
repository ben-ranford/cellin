"""Candidate generation for deterministic memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, replace

from cellin.core import GraphStore, MemoryAtom, MemoryEdge, MemoryStore, VectorStore
from cellin.stores.vector_utils import tokenize


def _lexical_seed_score(query: str, memory: MemoryAtom) -> float:
    query_tokens = tokenize(query)
    memory_tokens = tokenize(memory.text)
    if not query_tokens or not memory_tokens:
        return 0.0

    overlap = query_tokens & memory_tokens
    if not overlap:
        return 0.0

    return len(overlap) / len(query_tokens)


def _annotate_distance(memory: MemoryAtom, distance: int) -> MemoryAtom:
    return replace(
        memory,
        metadata={**memory.metadata, "graph_distance": distance},
    )


def _annotate_vector_score(memory: MemoryAtom, score: float) -> MemoryAtom:
    return replace(
        memory,
        metadata={**memory.metadata, "vector_score": round(max(score, 0.0), 6)},
    )


def _ordered_unique(memories: list[MemoryAtom]) -> list[MemoryAtom]:
    ordered: list[MemoryAtom] = []
    seen: set[str] = set()
    for memory in memories:
        if memory.memory_id in seen:
            continue
        seen.add(memory.memory_id)
        ordered.append(memory)
    return ordered


@dataclass(slots=True)
class RetrievalCandidateGenerator:
    """Generates retrieval candidates from lexical, vector, and graph signals."""

    memory_store: MemoryStore
    graph_store: GraphStore | None = None
    vector_store: VectorStore | None = None
    lexical_limit: int = 4
    vector_limit: int = 4

    def collect(self, query: str, *, limit: int) -> tuple[MemoryAtom, ...]:
        memories = self._active_memories()
        if not memories or limit <= 0:
            return ()

        ranked_by_seed = self._rank_by_lexical_seed(query, memories)
        ranked_by_vector = self._rank_by_vector_seed(query, memories)
        seed_candidates = self._seed_candidates(
            query,
            ranked_by_seed,
            ranked_by_vector,
            limit,
        )
        candidates = self._candidate_index(seed_candidates)
        self._expand_graph_neighbors(seed_candidates, candidates)
        return self._assemble_ordered_candidates(ranked_by_seed, candidates, limit)

    def _active_memories(self) -> tuple[MemoryAtom, ...]:
        return tuple(memory for memory in self.memory_store.list() if not memory.decay.archived)

    def _rank_by_lexical_seed(
        self,
        query: str,
        memories: tuple[MemoryAtom, ...],
    ) -> list[MemoryAtom]:
        return sorted(
            memories,
            key=lambda memory: _lexical_seed_score(query, memory),
            reverse=True,
        )

    def _seed_candidates(
        self,
        query: str,
        ranked_by_seed: list[MemoryAtom],
        ranked_by_vector: tuple[MemoryAtom, ...],
        limit: int,
    ) -> list[MemoryAtom]:
        if limit <= 0:
            return []

        lexical_seeded = [
            _annotate_distance(memory, 0)
            for memory in ranked_by_seed[: self.lexical_limit]
            if _lexical_seed_score(query, memory) > 0.0
        ]
        vector_seeded = [_annotate_distance(memory, 0) for memory in ranked_by_vector]
        if lexical_seeded:
            seed_candidates = list(lexical_seeded) + vector_seeded
            return seed_candidates[: max(limit, self.vector_limit, self.lexical_limit)]

        if vector_seeded:
            return vector_seeded[: max(limit, self.vector_limit)]

        return self._fallback_seed_candidates(ranked_by_seed, limit)

    def _fallback_seed_candidates(
        self,
        ranked_by_seed: list[MemoryAtom],
        limit: int,
    ) -> list[MemoryAtom]:
        return [
            _annotate_distance(memory, 0)
            for memory in ranked_by_seed[: min(limit, self.lexical_limit)]
        ]

    def _rank_by_vector_seed(
        self,
        query: str,
        memories: tuple[MemoryAtom, ...],
    ) -> tuple[MemoryAtom, ...]:
        if self.vector_store is None:
            return ()

        active = {memory.memory_id: memory for memory in memories}
        matches = self.vector_store.search(
            query,
            limit=max(self.vector_limit, 1),
        )
        vector_candidates: list[MemoryAtom] = []
        for match in matches:
            memory = active.get(match.memory_id)
            if memory is None:
                continue
            vector_candidates.append(_annotate_vector_score(memory, match.score))

        ranked_candidates = sorted(
            vector_candidates,
            key=lambda item: (item.metadata["vector_score"], item.memory_id),
            reverse=True,
        )
        return tuple(_ordered_unique(ranked_candidates))

    def _candidate_index(self, seed_candidates: list[MemoryAtom]) -> dict[str, MemoryAtom]:
        merged: dict[str, MemoryAtom] = {}
        for memory in seed_candidates:
            existing = merged.get(memory.memory_id)
            if existing is None:
                merged[memory.memory_id] = memory
                continue

            merged[memory.memory_id] = replace(
                existing,
                metadata={**existing.metadata, **memory.metadata},
            )

        return merged

    def _expand_graph_neighbors(
        self,
        seed_candidates: list[MemoryAtom],
        candidates: dict[str, MemoryAtom],
    ) -> None:
        if self.graph_store is None:
            return

        for seed in seed_candidates:
            for edge in self.graph_store.neighbors(seed.memory_id):
                neighbor = self._resolve_neighbor(seed.memory_id, edge, candidates)
                if neighbor is None:
                    continue
                candidates[neighbor.memory_id] = _annotate_distance(neighbor, 1)

    def _resolve_neighbor(
        self,
        seed_memory_id: str,
        edge: MemoryEdge,
        candidates: dict[str, MemoryAtom],
    ) -> MemoryAtom | None:
        neighbor_id = edge.target_id if edge.source_id == seed_memory_id else edge.source_id
        if neighbor_id in candidates:
            return None

        neighbor = self._get_neighbor_memory(neighbor_id)
        if neighbor is None or neighbor.decay.archived:
            return None

        return neighbor

    def _get_neighbor_memory(self, neighbor_id: str) -> MemoryAtom | None:
        if self.graph_store is not None:
            neighbor = self.graph_store.get_memory(neighbor_id)
            if neighbor is not None:
                return neighbor
        return self.memory_store.get(neighbor_id)

    def _assemble_ordered_candidates(
        self,
        ranked_by_seed: list[MemoryAtom],
        candidates: dict[str, MemoryAtom],
        limit: int,
    ) -> tuple[MemoryAtom, ...]:
        ordered: list[MemoryAtom] = []
        selected_ids: set[str] = set()

        for memory in ranked_by_seed:
            memory_id = memory.memory_id
            if memory_id in selected_ids:
                continue
            ordered.append(candidates.get(memory_id, memory))
            selected_ids.add(memory_id)
            if len(ordered) >= limit:
                return tuple(ordered[:limit])

        for memory in candidates.values():
            memory_id = memory.memory_id
            if memory_id in selected_ids:
                continue
            ordered.append(memory)
            selected_ids.add(memory_id)
            if len(ordered) >= limit:
                break

        return tuple(ordered[:limit])
