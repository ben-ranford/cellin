"""Additional ranking coverage for edge conditions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cellin.core import DecayState, MemoryAtom, MemoryKind, Modality, Provenance, RetrievalStats
from cellin.ranking import WeightedRanker, get_weight_profile


def _memory(text: str, *, metadata: dict[str, object] | None = None) -> MemoryAtom:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    metadata_values = {} if metadata is None else metadata
    return MemoryAtom(
        memory_id="memory-1",
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id="memory-1", source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
        metadata=metadata_values,
    )


def test_weight_profile_lookup_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="Unknown retrieval weight profile"):
        get_weight_profile("unknown")


def test_weighted_ranker_handles_empty_query_tokens() -> None:
    ranker = WeightedRanker(profile=get_weight_profile("balanced"))

    scored = ranker.score("!!!", (_memory("Atlas retrieval"),))

    assert scored[0].factors[0].name == "semantic_similarity"
    assert scored[0].factors[0].value == pytest.approx(0.0)


def test_weighted_ranker_includes_vector_similarity_factor() -> None:
    ranker = WeightedRanker(profile=get_weight_profile("balanced"))

    scored = ranker.score(
        "irrelevant query",
        (_memory("Atlas retrieval", metadata={"vector_score": 0.77}),),
    )

    assert scored[0].factors[7].name == "vector_similarity"
    assert scored[0].factors[7].value == pytest.approx(0.77)
    assert scored[0].factors[7].rationale.startswith("Vector-space similarity")
