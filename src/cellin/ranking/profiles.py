"""Built-in weighting profiles for deterministic retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeightProfile:
    """A named set of factor weights for retrieval ranking."""

    name: str
    semantic_similarity: float
    graph_proximity: float
    recency: float
    salience: float
    trust: float
    reinforcement: float
    modality_match: float
    token_budget: int = 120
    candidate_limit: int = 8
    recency_half_life_days: float = 14.0


PROFILES: dict[str, WeightProfile] = {
    "balanced": WeightProfile(
        name="balanced",
        semantic_similarity=0.28,
        graph_proximity=0.18,
        recency=0.12,
        salience=0.18,
        trust=0.08,
        reinforcement=0.08,
        modality_match=0.08,
    ),
    "recency_sensitive": WeightProfile(
        name="recency_sensitive",
        semantic_similarity=0.22,
        graph_proximity=0.10,
        recency=0.30,
        salience=0.14,
        trust=0.08,
        reinforcement=0.08,
        modality_match=0.08,
        recency_half_life_days=5.0,
    ),
    "concept_sensitive": WeightProfile(
        name="concept_sensitive",
        semantic_similarity=0.30,
        graph_proximity=0.24,
        recency=0.06,
        salience=0.16,
        trust=0.08,
        reinforcement=0.08,
        modality_match=0.08,
        recency_half_life_days=21.0,
    ),
}


def get_weight_profile(name: str) -> WeightProfile:
    """Return a built-in profile by name."""

    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown retrieval weight profile: {name}") from exc
