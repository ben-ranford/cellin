"""Additional ranking coverage for edge conditions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cellin.core import DecayState, MemoryAtom, MemoryKind, Modality, Provenance, RetrievalStats
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.ranking.profiles import PROFILES, WeightProfile


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


# ---------------------------------------------------------------------------
# Weight normalisation tests (#148)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile_name", list(PROFILES))
def test_weighted_ranker_normalises_builtin_profile_weights(profile_name: str) -> None:
    """WeightedRanker stores the correct weight total for normalisation."""
    profile = get_weight_profile(profile_name)
    ranker = WeightedRanker(profile=profile)
    expected_total = (
        profile.semantic_similarity
        + profile.vector_similarity
        + profile.graph_proximity
        + profile.recency
        + profile.salience
        + profile.trust
        + profile.reinforcement
        + profile.modality_match
    )
    assert ranker._weight_total == pytest.approx(expected_total), (
        f"Profile '{profile_name}': _weight_total {ranker._weight_total!r} != {expected_total!r}"
    )
    assert ranker._weight_total > 0.0


def test_weighted_ranker_score_bounded_for_perfect_memory() -> None:
    """A memory with all component scores at maximum must produce score in [0, 1]."""
    # Use a query identical to the memory text so semantic_similarity is maximal.
    # Set vector_score=1.0, graph_distance=0 (proximity=1.0), access_count=10,
    # salience_score and trust_score default to 1.0.
    now = datetime(2026, 4, 5, tzinfo=UTC)
    perfect_memory = MemoryAtom(
        memory_id="perfect",
        kind=MemoryKind.ATOM,
        text="perfect memory text",
        provenance=Provenance(source_id="perfect", source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(access_count=10),
        metadata={"vector_score": 1.0, "graph_distance": 0},
        salience_score=1.0,
        trust_score=1.0,
    )

    for profile_name in PROFILES:
        ranker = WeightedRanker(
            profile=get_weight_profile(profile_name),
            now_provider=lambda: now,
        )
        scored = ranker.score("perfect memory text", (perfect_memory,))
        score = scored[0].score
        assert 0.0 <= score <= 1.0, f"Profile '{profile_name}': score {score} is outside [0, 1]"


def test_weight_profile_rejects_negative_weights() -> None:
    """WeightProfile must raise ValueError if any factor weight is negative."""
    with pytest.raises(ValueError, match="negative factor weights"):
        WeightProfile(
            name="bad",
            semantic_similarity=-0.1,
            vector_similarity=0.2,
            graph_proximity=0.2,
            recency=0.2,
            salience=0.2,
            trust=0.1,
            reinforcement=0.05,
            modality_match=0.05,
        )


def test_weighted_ranker_normalises_custom_profile() -> None:
    """WeightedRanker correctly stores _weight_total for user-supplied profiles."""
    profile = WeightProfile(
        name="custom",
        semantic_similarity=2.0,
        vector_similarity=2.0,
        graph_proximity=2.0,
        recency=2.0,
        salience=2.0,
        trust=2.0,
        reinforcement=2.0,
        modality_match=8.0,
    )
    ranker = WeightedRanker(profile=profile)
    assert ranker._weight_total == pytest.approx(22.0)
    # Score must still be bounded in [0, 1] for any valid factor values.
    assert ranker.profile is profile
