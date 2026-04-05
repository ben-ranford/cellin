"""Additional coverage for retrieval candidate generation internals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from unittest.mock import create_autospec

from cellin.core import (
    DecayState,
    MemoryAtom,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
    RetrievalStats,
    VectorMatch,
)
from cellin.retrieval import RetrievalCandidateGenerator


def _memory(
    memory_id: str,
    *,
    text: str = "atlas",
    metadata: dict[str, object] | None = None,
) -> MemoryAtom:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
        metadata=metadata or {},
    )


@dataclass(slots=True)
class _UnknownIdVectorStore:
    memory: str

    def upsert(self, memory_id: str, text: str) -> None:
        del memory_id, text

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        del query
        return (VectorMatch(memory_id=self.memory, score=0.7),)[: max(0, limit)]


def _memory_store(memories: tuple[MemoryAtom, ...]) -> MemoryStore:
    indexed = {memory.memory_id: memory for memory in memories}
    memory_store = create_autospec(MemoryStore, instance=True)
    memory_store.list.return_value = memories
    memory_store.get.side_effect = indexed.get
    return memory_store


def test_seed_candidates_returns_empty_for_non_positive_limit() -> None:
    generator = RetrievalCandidateGenerator(memory_store=_memory_store(()))
    assert (
        generator._seed_candidates(
            query="atlas",
            ranked_by_seed=[],
            ranked_by_vector=(),
            limit=0,
        )
        == []
    )


def test_rank_by_vector_seed_skips_unknown_memory_ids() -> None:
    generator = RetrievalCandidateGenerator(
        memory_store=_memory_store((_memory("known"),)),
        vector_store=_UnknownIdVectorStore("missing"),
    )

    candidates = generator._rank_by_vector_seed("atlas", (_memory("known"),))

    assert candidates == ()


def test_candidate_index_merges_duplicate_candidates() -> None:
    generator = RetrievalCandidateGenerator(memory_store=_memory_store(()))
    candidate = generator._candidate_index(
        [
            _memory("same", metadata={"from_seed": True}),
            replace(_memory("same"), metadata={"from_graph": True}),
        ]
    )

    merged = candidate["same"]
    assert merged.metadata["from_seed"] is True
    assert merged.metadata["from_graph"] is True


def test_expand_graph_neighbors_noop_when_graph_store_is_missing() -> None:
    seed_candidates = [_memory("seed")]
    candidates = {_memory("seed").memory_id: _memory("seed")}
    generator = RetrievalCandidateGenerator(memory_store=_memory_store((_memory("seed"),)))

    generator._expand_graph_neighbors(seed_candidates, candidates)

    assert candidates == {_memory("seed").memory_id: _memory("seed")}


def test_get_neighbor_memory_falls_back_to_memory_store() -> None:
    memory = _memory("fallback")
    generator = RetrievalCandidateGenerator(memory_store=_memory_store((memory,)))

    assert generator._get_neighbor_memory(memory.memory_id) == memory


def test_assemble_ordered_candidates_dedupes_ranked_memories_and_adds_missing_candidates() -> None:
    ranked_by_seed = [_memory("first"), _memory("second"), _memory("second")]
    candidates = {
        "first": _memory("first"),
        "second": _memory("second"),
        "third": _memory("third"),
    }
    generator = RetrievalCandidateGenerator(memory_store=_memory_store(tuple(candidates.values())))

    ordered = generator._assemble_ordered_candidates(ranked_by_seed, candidates, limit=3)

    assert tuple(memory.memory_id for memory in ordered) == ("first", "second", "third")
