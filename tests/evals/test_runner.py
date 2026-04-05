"""Tests for the deterministic eval runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import cellin.evals.runner as eval_runner
from cellin.core import (
    DecayState,
    MemoryAtom,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
    VectorMatch,
    VectorStore,
)
from cellin.evals.runner import run_evaluation_suite


def _memory(memory_id: str, observed_at: datetime) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=f"{memory_id} memory text",
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=observed_at,
        observed_at=observed_at,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


class _VectorStore(VectorStore):
    def __init__(self) -> None:
        self.calls = 0

    def upsert(self, memory_id: str, text: str) -> None:
        pass

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        del query
        return (
            VectorMatch(memory_id="memory-b", score=0.98),
            VectorMatch(memory_id="memory-a", score=0.11),
        )[: max(0, limit)]


def test_smoke_suite_writes_report_with_deltas(tmp_path: Path) -> None:
    output_path = tmp_path / "smoke.json"

    report = run_evaluation_suite("smoke", output_path=output_path)

    assert report.status == "ok"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["suite"] == "smoke"
    assert payload["summary_metrics"]["case_count"] == 3.0
    assert payload["cases"][2]["case_id"] == "dream-atlas"
    assert "delta_metrics" in payload["cases"][2]


def test_full_suite_includes_performance_and_contradiction_cases(tmp_path: Path) -> None:
    output_path = tmp_path / "full.json"

    report = run_evaluation_suite("full", output_path=output_path)

    case_ids = tuple(case.case_id for case in report.cases)
    assert report.status == "ok"
    assert case_ids[-2:] == ("contradiction-repair", "performance-dedup")
    performance_case = report.cases[-1]
    assert performance_case.delta_metrics["active_memories"] < 0.0
    assert performance_case.delta_metrics["bundle_tokens"] < 0.0


def test_runner_retriever_exposes_vector_signal_in_ranking() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    memories = (_memory("memory-a", now), _memory("memory-b", now))
    retriever = eval_runner._retriever(
        eval_runner._InMemoryMemoryStore(memories),
        eval_runner._InMemoryGraphStore(memories, ()),
        "balanced",
        vector_store=_VectorStore(),
    )

    bundle = retriever.retrieve("atlas retrieval", top_k=2)

    assert bundle.memories[0].memory.memory_id == "memory-b"
    assert bundle.memories[0].factors[7].name == "vector_similarity"
