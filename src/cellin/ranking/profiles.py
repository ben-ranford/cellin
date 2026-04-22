"""Built-in weighting profiles for deterministic retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeightProfile:
    """A named set of factor weights for retrieval ranking.

    Factor weights do not need to sum to 1.0 — ``WeightedRanker`` normalises
    them automatically at construction time.  However, all weights must be
    non-negative; a ``ValueError`` is raised on construction if any weight is
    negative.
    """

    name: str
    semantic_similarity: float
    vector_similarity: float
    graph_proximity: float
    recency: float
    salience: float
    trust: float
    reinforcement: float
    modality_match: float
    token_budget: int = 120
    candidate_limit: int = 8
    recency_half_life_days: float = 14.0

    def __post_init__(self) -> None:
        factor_weights = {
            "semantic_similarity": self.semantic_similarity,
            "vector_similarity": self.vector_similarity,
            "graph_proximity": self.graph_proximity,
            "recency": self.recency,
            "salience": self.salience,
            "trust": self.trust,
            "reinforcement": self.reinforcement,
            "modality_match": self.modality_match,
        }
        negative = [name for name, w in factor_weights.items() if w < 0]
        if negative:
            raise ValueError(f"WeightProfile '{self.name}' has negative factor weights: {negative}")


PROFILES: dict[str, WeightProfile] = {
    "balanced": WeightProfile(
        name="balanced",
        semantic_similarity=0.24,
        vector_similarity=0.12,
        graph_proximity=0.18,
        recency=0.12,
        salience=0.18,
        trust=0.08,
        reinforcement=0.08,
        modality_match=0.08,
    ),
    "recency_sensitive": WeightProfile(
        name="recency_sensitive",
        semantic_similarity=0.18,
        vector_similarity=0.12,
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
        semantic_similarity=0.24,
        vector_similarity=0.12,
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
