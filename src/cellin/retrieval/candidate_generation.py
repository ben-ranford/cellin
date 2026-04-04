"""Candidate generation for deterministic memory retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from cellin.core import GraphStore, MemoryAtom, MemoryStore

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _lexical_seed_score(query: str, memory: MemoryAtom) -> float:
    query_tokens = _tokenize(query)
    memory_tokens = _tokenize(memory.text)
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


@dataclass(slots=True)
class RetrievalCandidateGenerator:
    """Generates retrieval candidates from lexical seeds plus graph expansion."""

    memory_store: MemoryStore
    graph_store: GraphStore | None = None
    lexical_limit: int = 4

    def collect(self, query: str, *, limit: int) -> tuple[MemoryAtom, ...]:
        memories = tuple(memory for memory in self.memory_store.list() if not memory.decay.archived)
        if not memories:
            return ()

        ranked_by_seed = sorted(
            memories,
            key=lambda memory: _lexical_seed_score(query, memory),
            reverse=True,
        )
        seed_candidates = [
            _annotate_distance(memory, 0)
            for memory in ranked_by_seed[: self.lexical_limit]
            if _lexical_seed_score(query, memory) > 0.0
        ]
        if not seed_candidates:
            seed_candidates = [
                _annotate_distance(memory, 0)
                for memory in ranked_by_seed[: min(limit, self.lexical_limit)]
            ]

        candidates: dict[str, MemoryAtom] = {memory.memory_id: memory for memory in seed_candidates}

        if self.graph_store is not None:
            for seed in seed_candidates:
                for edge in self.graph_store.neighbors(seed.memory_id):
                    neighbor_id = (
                        edge.target_id if edge.source_id == seed.memory_id else edge.source_id
                    )
                    if neighbor_id in candidates:
                        continue

                    neighbor = self.graph_store.get_memory(neighbor_id) or self.memory_store.get(
                        neighbor_id
                    )
                    if neighbor is None:
                        continue
                    if neighbor.decay.archived:
                        continue

                    candidates[neighbor_id] = _annotate_distance(neighbor, 1)
                    if len(candidates) >= limit:
                        break

        ordered_ids = [
            memory.memory_id for memory in ranked_by_seed if memory.memory_id in candidates
        ]
        ordered = tuple(candidates[memory_id] for memory_id in ordered_ids[:limit])
        if len(ordered) >= limit:
            return ordered

        missing = [memory for memory in ranked_by_seed if memory.memory_id not in candidates]
        return ordered + tuple(missing[: max(0, limit - len(ordered))])
