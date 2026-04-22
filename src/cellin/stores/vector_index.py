"""Deterministic in-memory vector index for local demos and tests."""

from __future__ import annotations

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class InMemoryVectorIndex:
    """A simple in-memory cosine-similarity index."""

    def __init__(self) -> None:
        self._vectors: dict[str, tuple[float, ...]] = {}

    def upsert(self, memory_id: str, text: str) -> None:
        self._vectors[memory_id] = vectorize(text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        results = [
            VectorMatch(
                memory_id=memory_id,
                score=round(cosine_similarity(query_vector, vector), 6),
            )
            for memory_id, vector in self._vectors.items()
        ]
        ordered = sorted(results, key=lambda result: (-result.score, result.memory_id))
        return tuple(ordered[:limit])

    def delete(self, memory_id: str) -> None:
        """Remove an indexed vector for a memory id if present."""
        self._vectors.pop(memory_id, None)


SearchResult = VectorMatch
