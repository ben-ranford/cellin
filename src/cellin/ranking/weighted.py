"""Deterministic weighted ranking for Cellin retrieval."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log1p

from cellin.core import FactorScore, MemoryAtom, Modality, ScoredMemory
from cellin.ranking.profiles import WeightProfile

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _semantic_similarity(query: str, memory: MemoryAtom) -> float:
    query_tokens = _tokenize(query)
    memory_tokens = _tokenize(memory.text)
    if not query_tokens or not memory_tokens:
        return 0.0

    overlap = query_tokens & memory_tokens
    union = query_tokens | memory_tokens
    jaccard = len(overlap) / len(union)
    substring_bonus = 0.15 if query.lower() in memory.text.lower() else 0.0
    return min(1.0, jaccard + substring_bonus)


def _graph_proximity(memory: MemoryAtom) -> float:
    raw_distance = memory.metadata.get("graph_distance")
    if not isinstance(raw_distance, int | float):
        return 0.0
    return 1.0 / (1.0 + float(raw_distance))


def _recency(memory: MemoryAtom, *, now: datetime, half_life_days: float) -> float:
    observed_at = memory.observed_at or memory.created_at
    age_days = max((now - observed_at).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + (age_days / half_life_days))


def _reinforcement(memory: MemoryAtom) -> float:
    return min(log1p(memory.retrieval.access_count) / log1p(10), 1.0)


def _modality_match(memory: MemoryAtom) -> float:
    if memory.modality in {Modality.TEXT, Modality.CHAT, Modality.MARKDOWN, Modality.JSON}:
        return 1.0
    return 0.4


def _vector_similarity(memory: MemoryAtom) -> float:
    raw_score = memory.metadata.get("vector_score")
    if not isinstance(raw_score, int | float) or isinstance(raw_score, bool):
        return 0.0

    return max(0.0, min(1.0, float(raw_score)))


@dataclass(slots=True)
class WeightedRanker:
    """Explainable weighted ranking over memory atoms.

    The factor weights in *profile* are normalised at construction time so that
    they sum to exactly 1.0.  This guarantees ``score`` returns a value in
    ``[0.0, 1.0]`` whenever all individual factor values are in ``[0.0, 1.0]``.
    """

    profile: WeightProfile
    now_provider: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        total = (
            self.profile.semantic_similarity
            + self.profile.vector_similarity
            + self.profile.graph_proximity
            + self.profile.recency
            + self.profile.salience
            + self.profile.trust
            + self.profile.reinforcement
            + self.profile.modality_match
        )
        if total == 0.0:
            raise ValueError(
                f"WeightProfile '{self.profile.name}' has all-zero factor weights; "
                "cannot normalise."
            )
        if total != 1.0:
            object.__setattr__(
                self,
                "profile",
                WeightProfile(
                    name=self.profile.name,
                    semantic_similarity=self.profile.semantic_similarity / total,
                    vector_similarity=self.profile.vector_similarity / total,
                    graph_proximity=self.profile.graph_proximity / total,
                    recency=self.profile.recency / total,
                    salience=self.profile.salience / total,
                    trust=self.profile.trust / total,
                    reinforcement=self.profile.reinforcement / total,
                    modality_match=self.profile.modality_match / total,
                    token_budget=self.profile.token_budget,
                    candidate_limit=self.profile.candidate_limit,
                    recency_half_life_days=self.profile.recency_half_life_days,
                ),
            )

    def score(self, query: str, memories: Sequence[MemoryAtom]) -> tuple[ScoredMemory, ...]:
        now = self.now_provider()
        scored: list[ScoredMemory] = []

        for memory in memories:
            factors = (
                FactorScore(
                    name="semantic_similarity",
                    value=_semantic_similarity(query, memory),
                    rationale="Token overlap and exact-substring matching.",
                ),
                FactorScore(
                    name="graph_proximity",
                    value=_graph_proximity(memory),
                    rationale="Candidate expansion distance from lexical seed memories.",
                ),
                FactorScore(
                    name="recency",
                    value=_recency(
                        memory,
                        now=now,
                        half_life_days=self.profile.recency_half_life_days,
                    ),
                    rationale="Age-decayed freshness score.",
                ),
                FactorScore(
                    name="salience",
                    value=memory.salience_score,
                    rationale="Importance carried on the memory object.",
                ),
                FactorScore(
                    name="trust",
                    value=memory.trust_score,
                    rationale="Reliability score carried on the memory object.",
                ),
                FactorScore(
                    name="reinforcement",
                    value=_reinforcement(memory),
                    rationale="Log-scaled retrieval reinforcement count.",
                ),
                FactorScore(
                    name="modality_match",
                    value=_modality_match(memory),
                    rationale="Prefer text-like modalities for text queries.",
                ),
                FactorScore(
                    name="vector_similarity",
                    value=_vector_similarity(memory),
                    rationale="Vector-space similarity from the hybrid retrieval pass.",
                ),
            )
            total = (
                self.profile.semantic_similarity * factors[0].value
                + self.profile.vector_similarity * factors[7].value
                + self.profile.graph_proximity * factors[1].value
                + self.profile.recency * factors[2].value
                + self.profile.salience * factors[3].value
                + self.profile.trust * factors[4].value
                + self.profile.reinforcement * factors[5].value
                + self.profile.modality_match * factors[6].value
            )
            scored.append(ScoredMemory(memory=memory, score=round(total, 6), factors=factors))

        return tuple(sorted(scored, key=lambda item: item.score, reverse=True))
