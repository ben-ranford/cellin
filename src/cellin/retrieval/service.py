"""Retrieval service that assembles explainable memory bundles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from cellin.core import MemoryBundle, MemoryStore, ScoredMemory, VectorStore
from cellin.ranking.profiles import WeightProfile
from cellin.ranking.weighted import WeightedRanker
from cellin.retrieval.candidate_generation import RetrievalCandidateGenerator


def _estimate_token_cost(item: ScoredMemory) -> int:
    metadata_cost = item.memory.metadata.get("token_count")
    if isinstance(metadata_cost, int):
        return max(1, metadata_cost)
    return max(1, len(item.memory.text.split()))


@dataclass(slots=True)
class WeightedRetriever:
    """Retrieves explainable memory bundles from candidate memory atoms."""

    candidate_generator: RetrievalCandidateGenerator
    ranker: WeightedRanker
    profile: WeightProfile
    memory_store: MemoryStore | None = None
    representation_store: VectorStore | None = None

    def __post_init__(self) -> None:
        # Wire representation_store into the candidate generator when the generator
        # has no primary vector_store configured.
        if self.representation_store is not None and self.candidate_generator.vector_store is None:
            self.candidate_generator.vector_store = self.representation_store

    def retrieve(self, query: str, top_k: int = 5) -> MemoryBundle:
        if top_k <= 0:
            return MemoryBundle(
                query=query,
                memories=(),
                total_score=0.0,
                summary=None,
                token_budget=self.profile.token_budget,
            )

        candidates = self.candidate_generator.collect(
            query,
            limit=max(top_k, self.profile.candidate_limit),
        )
        ranked = self.ranker.score(query, candidates)
        selected = self._fit_to_budget(ranked[:top_k], token_budget=self.profile.token_budget)
        self._write_back_access(list(selected))
        total_score = round(sum(item.score for item in selected), 6)
        summary = ", ".join(item.memory.memory_id for item in selected) if selected else None
        return MemoryBundle(
            query=query,
            memories=selected,
            total_score=total_score,
            summary=summary,
            token_budget=self.profile.token_budget,
        )

    def _write_back_access(self, memories: list[ScoredMemory]) -> None:
        """Increment access_count and update last_accessed_at for selected memories."""
        if self.memory_store is None:
            return
        now = datetime.now(UTC)
        for m in memories:
            updated_retrieval = replace(
                m.memory.retrieval,
                access_count=m.memory.retrieval.access_count + 1,
                last_accessed_at=now,
            )
            updated_memory = replace(m.memory, retrieval=updated_retrieval)
            self.memory_store.put(updated_memory)

    def _fit_to_budget(
        self,
        ranked: tuple[ScoredMemory, ...],
        *,
        token_budget: int,
    ) -> tuple[ScoredMemory, ...]:
        """Select ranked memories whose cumulative token cost never exceeds budget."""
        if token_budget <= 0:
            return ()

        selected: list[ScoredMemory] = []
        consumed = 0

        for item in ranked:
            cost = _estimate_token_cost(item)
            # Never include a memory that would exceed the remaining budget,
            # including the top-ranked candidate when it is oversized.
            if consumed + cost > token_budget:
                continue
            selected.append(item)
            consumed += cost
            if consumed >= token_budget:
                break

        return tuple(selected)
