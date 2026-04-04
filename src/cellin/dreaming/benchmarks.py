"""Dream benchmark metadata used by tests and evals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DreamBenchmarkCase:
    """A deterministic retrieval-improvement check over a dream corpus."""

    benchmark_id: str
    query: str
    expected_top_memory_id_after: str
    minimum_score_gain: float


def seeded_dream_benchmark_cases() -> tuple[DreamBenchmarkCase, ...]:
    return (
        DreamBenchmarkCase(
            benchmark_id="atlas-summary-improves-combined-query",
            query="How does Atlas consolidate multimodal memory for retrieval?",
            expected_top_memory_id_after="dream-atlas-20260404000000",
            minimum_score_gain=0.03,
        ),
    )
