"""Installed benchmark definitions for retrieval quality."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalBenchmarkCase:
    """A retrieval benchmark expectation over a seeded corpus."""

    name: str
    query: str
    profile_name: str
    expected_memory_ids: tuple[str, ...]
    top_k: int


def seeded_benchmark_cases() -> tuple[RetrievalBenchmarkCase, ...]:
    """Return deterministic benchmark cases for the current retrieval MVP."""

    return (
        RetrievalBenchmarkCase(
            name="concept-aware-atlas",
            query="How does Atlas architecture support memory graphs?",
            profile_name="concept_sensitive",
            expected_memory_ids=("atlas-arch", "atlas-vision"),
            top_k=2,
        ),
        RetrievalBenchmarkCase(
            name="recent-deployment",
            query="What happened yesterday with the deployment?",
            profile_name="recency_sensitive",
            expected_memory_ids=("deploy-yesterday",),
            top_k=1,
        ),
    )
