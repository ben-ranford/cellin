"""Tests for the deterministic eval runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import cellin.evals.runner as eval_runner
from cellin.core import (
    DecayState,
    MemoryAtom,
    MemoryBundle,
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
        self.calls += 1
        del memory_id, text

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
    assert payload["summary_metrics"]["case_count"] == pytest.approx(3.0)
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


def test_retrieval_case_with_empty_bundle_does_not_index_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyRetriever:
        def retrieve(self, query: str, top_k: int = 5) -> MemoryBundle:
            del query, top_k
            return MemoryBundle(query="atlas retrieval", memories=(), total_score=0.0)

    monkeypatch.setattr(eval_runner, "_retriever", lambda *args, **kwargs: _EmptyRetriever())
    case = eval_runner._run_retrieval_case(
        benchmark_index=0,
        corpus_name="project_memory",
        case_id="retrieval-project",
    )
    assert case.status == "failed"
    assert case.metrics["top_score"] == 0.0
    assert case.metrics["hit_rate"] == 0.0


def test_dream_case_with_empty_bundle_reports_failure_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyRetriever:
        def retrieve(self, query: str, top_k: int = 5) -> MemoryBundle:
            del query, top_k
            return MemoryBundle(query="atlas planning", memories=(), total_score=0.0)

    monkeypatch.setattr(eval_runner, "_retriever", lambda *args, **kwargs: _EmptyRetriever())
    case = eval_runner._run_dream_case()
    assert case.status == "failed"
    assert case.metrics["top_score"] == 0.0
    assert case.notes["diff"]


def test_ingest_case_with_empty_vector_output_is_hardened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyVectorStore:
        def search(self, query: str, *, limit: int = 5) -> tuple[object, ...]:
            del query, limit
            return ()

    class _MemoryBundle:
        def __init__(self) -> None:
            self.vector_store = _EmptyVectorStore()
            self.graph_store = SimpleNamespace()
            self.memory_store = SimpleNamespace()

    class _FakeIngestor:
        @classmethod
        def with_built_in_adapters(
            cls, graph_store: object, memory_store: object, vector_store: object
        ) -> _FakeIngestor:
            del graph_store, memory_store, vector_store
            return cls()

        def ingest_envelopes(self, envelopes: tuple[object, ...]) -> SimpleNamespace:
            del envelopes
            return SimpleNamespace(memories=(1, 2, 3, 4), edges=(1, 2))

    monkeypatch.setattr(
        eval_runner, "build_storage_bundle", lambda *args, **kwargs: _MemoryBundle()
    )
    monkeypatch.setattr(
        eval_runner.CanonicalIngestor,
        "with_built_in_adapters",
        _FakeIngestor.with_built_in_adapters,
    )

    case = eval_runner._run_ingest_case()
    assert case.status == "ok"
    assert case.metrics["vector_top_score"] == 0.0
    assert case.notes["top_memory_id"] is None
