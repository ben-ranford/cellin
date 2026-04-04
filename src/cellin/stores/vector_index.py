"""Deterministic in-memory vector index for local demos and tests."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[a-z0-9]+")
VECTOR_SIZE = 12


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _vectorize(text: str) -> tuple[float, ...]:
    buckets = [0.0] * VECTOR_SIZE
    for token in _tokenize(text):
        buckets[hash(token) % VECTOR_SIZE] += 1.0
    norm = math.sqrt(sum(value * value for value in buckets))
    if norm == 0:
        return tuple(buckets)
    return tuple(value / norm for value in buckets)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A deterministic vector-index search match."""

    memory_id: str
    score: float


class InMemoryVectorIndex:
    """A simple in-memory cosine-similarity index."""

    def __init__(self) -> None:
        self._vectors: dict[str, tuple[float, ...]] = {}

    def upsert(self, memory_id: str, text: str) -> None:
        self._vectors[memory_id] = _vectorize(text)

    def search(self, query: str, *, limit: int = 5) -> tuple[SearchResult, ...]:
        query_vector = _vectorize(query)
        results = [
            SearchResult(
                memory_id=memory_id,
                score=round(
                    sum(a * b for a, b in zip(query_vector, vector, strict=True)),
                    6,
                ),
            )
            for memory_id, vector in self._vectors.items()
        ]
        ordered = sorted(results, key=lambda result: result.score, reverse=True)
        return tuple(ordered[:limit])
