"""Deterministic eval runner for Cellin's local-first quality gates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cellin.core import (
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryStore,
    Provenance,
    ScoredMemory,
)
from cellin.core.models import JSONValue
from cellin.dreaming import (
    AbstractionDreamStrategy,
    ContradictionRepairDreamStrategy,
    DeduplicationDreamStrategy,
    DreamRunner,
    seeded_dream_benchmark_cases,
)
from cellin.evals.assets import load_envelope_corpus, load_memory_corpus, load_memory_records
from cellin.evals.retrieval_benchmarks import seeded_benchmark_cases
from cellin.ingest import CanonicalIngestor
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore


def _json_float_map(values: dict[str, float]) -> dict[str, JSONValue]:
    return {key: value for key, value in values.items()}


def _token_cost(bundle_memories: tuple[ScoredMemory, ...]) -> float:
    total = 0
    for item in bundle_memories:
        memory = item.memory
        token_count = memory.metadata.get("token_count")
        if isinstance(token_count, int):
            total += token_count
            continue
        total += len(memory.text.split())
    return float(total)


class _InMemoryMemoryStore(MemoryStore):
    def __init__(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}

    def put(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self._memories.values())


class _InMemoryGraphStore(GraphStore):
    def __init__(
        self,
        memories: tuple[MemoryAtom, ...],
        edges: tuple[MemoryEdge, ...] = (),
    ) -> None:
        self._memories = {memory.memory_id: memory for memory in memories}
        self._edges = {edge.edge_id: edge for edge in edges}

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges[edge.edge_id] = edge

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self.list_edges()
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge for edge in self._edges.values() if edge.metadata.get("archived") is not True
        )


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    """One deterministic evaluation result."""

    case_id: str
    status: str
    metrics: dict[str, float]
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    delta_metrics: dict[str, float] = field(default_factory=dict)
    notes: dict[str, JSONValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        metrics = _json_float_map(self.metrics)
        baseline_metrics = _json_float_map(self.baseline_metrics)
        delta_metrics = _json_float_map(self.delta_metrics)
        return {
            "case_id": self.case_id,
            "status": self.status,
            "metrics": metrics,
            "baseline_metrics": baseline_metrics,
            "delta_metrics": delta_metrics,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """A machine-readable eval report for CI or nightly runs."""

    suite: str
    status: str
    generated_at: datetime
    cases: tuple[EvaluationCaseResult, ...]
    summary_metrics: dict[str, float]
    output_path: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        cases: list[JSONValue] = [case.to_dict() for case in self.cases]
        return {
            "suite": self.suite,
            "status": self.status,
            "generated_at": self.generated_at.isoformat(),
            "summary_metrics": _json_float_map(self.summary_metrics),
            "cases": cases,
            "output_path": self.output_path,
        }


def _delta(metrics: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    return {key: round(metrics[key] - baseline[key], 6) for key in metrics.keys() & baseline.keys()}


def _retriever(
    memory_store: MemoryStore, graph_store: GraphStore, profile_name: str
) -> WeightedRetriever:
    profile = get_weight_profile(profile_name)
    return WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(memory_store, graph_store),
        ranker=WeightedRanker(
            profile=profile,
            now_provider=lambda: datetime(2026, 4, 4, tzinfo=UTC),
        ),
        profile=profile,
    )


def _project_edges() -> tuple[MemoryEdge, ...]:
    return (
        MemoryEdge(
            edge_id="supports:atlas-arch:atlas-vision",
            source_id="atlas-arch",
            target_id="atlas-vision",
            kind=EdgeKind.SUPPORTS,
            provenance=Provenance(source_id="project-memory", source_type="eval-corpus"),
            created_at=datetime(2026, 3, 28, tzinfo=UTC),
            metadata={"label": "atlas"},
        ),
    )


def _run_ingest_case() -> EvaluationCaseResult:
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "cellin.sqlite"
        graph_store = SQLiteGraphStore(str(database_path))
        memory_store = SQLiteMemoryStore(str(database_path))
        vector_index = InMemoryVectorIndex()
        ingestor = CanonicalIngestor.with_built_in_adapters(
            graph_store=graph_store,
            memory_store=memory_store,
            vector_index=vector_index,
        )
        result = ingestor.ingest_envelopes(load_envelope_corpus("multimodal_artifacts"))
        vector_results = vector_index.search("memory graph retrieval pipeline", limit=1)
        metrics = {
            "memory_count": float(len(result.memories)),
            "edge_count": float(len(result.edges)),
            "vector_top_score": vector_results[0].score,
        }
        baseline = {"memory_count": 4.0, "edge_count": 2.0, "vector_top_score": 0.0}
        status = (
            "ok" if metrics["memory_count"] == 4.0 and metrics["edge_count"] >= 2.0 else "failed"
        )
        return EvaluationCaseResult(
            case_id="ingest-multimodal",
            status=status,
            metrics=metrics,
            baseline_metrics=baseline,
            delta_metrics=_delta(metrics, baseline),
            notes={"top_memory_id": vector_results[0].memory_id},
        )


def _run_retrieval_case(
    *, benchmark_index: int, corpus_name: str, case_id: str
) -> EvaluationCaseResult:
    benchmark = seeded_benchmark_cases()[benchmark_index]
    memories = load_memory_corpus(corpus_name)
    graph_store = _InMemoryGraphStore(
        memories, _project_edges() if corpus_name == "project_memory" else ()
    )
    memory_store = _InMemoryMemoryStore(memories)
    bundle = _retriever(memory_store, graph_store, benchmark.profile_name).retrieve(
        benchmark.query,
        top_k=benchmark.top_k,
    )
    actual_ids = tuple(item.memory.memory_id for item in bundle.memories)
    hit_rate = float(actual_ids == benchmark.expected_memory_ids)
    metrics = {"hit_rate": hit_rate, "top_score": bundle.memories[0].score}
    baseline = {"hit_rate": 1.0}
    return EvaluationCaseResult(
        case_id=case_id,
        status="ok" if hit_rate == 1.0 else "failed",
        metrics=metrics,
        baseline_metrics=baseline,
        delta_metrics=_delta(metrics, baseline),
        notes={
            "expected_memory_ids": list(benchmark.expected_memory_ids),
            "actual_memory_ids": list(actual_ids),
        },
    )


def _run_dream_case() -> EvaluationCaseResult:
    benchmark = seeded_dream_benchmark_cases()[0]
    memories = load_memory_records("evals/fixtures/dreaming/atlas_corpus.json")
    memory_store = _InMemoryMemoryStore(memories)
    graph_store = _InMemoryGraphStore(memories)
    retriever = _retriever(memory_store, graph_store, "balanced")
    before = retriever.retrieve(benchmark.query, top_k=1)
    result = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"abstraction": AbstractionDreamStrategy()},
    ).run_strategy("abstraction", at=datetime(2026, 4, 4, tzinfo=UTC))
    after = retriever.retrieve(benchmark.query, top_k=1)
    assert result is not None
    metrics = {
        "top_score": after.total_score,
        "bundle_tokens": _token_cost(after.memories),
        "score_gain": round(after.total_score - before.total_score, 6),
    }
    baseline = {
        "top_score": before.total_score,
        "bundle_tokens": _token_cost(before.memories),
        "score_gain": 0.0,
    }
    status = (
        "ok"
        if after.memories[0].memory.memory_id == benchmark.expected_top_memory_id_after
        and metrics["score_gain"] >= benchmark.minimum_score_gain
        else "failed"
    )
    return EvaluationCaseResult(
        case_id="dream-atlas",
        status=status,
        metrics=metrics,
        baseline_metrics=baseline,
        delta_metrics=_delta(metrics, baseline),
        notes={"diff": result.diff.to_dict()},
    )


def _run_contradiction_case() -> EvaluationCaseResult:
    memories = load_memory_corpus("contradiction_memory")
    memory_store = _InMemoryMemoryStore(memories)
    graph_store = _InMemoryGraphStore(memories)
    result = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"contradiction_repair": ContradictionRepairDreamStrategy()},
    ).run_strategy("contradiction_repair", at=datetime(2026, 4, 4, tzinfo=UTC))
    older = memory_store.get("atlas-rollout-green")
    assert result is not None
    assert older is not None
    metrics = {
        "contradiction_edges": float(len(graph_store.list_edges())),
        "older_trust": older.trust_score,
    }
    baseline = {"contradiction_edges": 0.0, "older_trust": 0.95}
    return EvaluationCaseResult(
        case_id="contradiction-repair",
        status="ok"
        if metrics["contradiction_edges"] == 1.0 and older.trust_score < 0.95
        else "failed",
        metrics=metrics,
        baseline_metrics=baseline,
        delta_metrics=_delta(metrics, baseline),
        notes={"affected_memory_ids": list(result.artifact.affected_memory_ids)},
    )


def _run_performance_case() -> EvaluationCaseResult:
    memories = load_memory_corpus("conversation_memory")
    memory_store = _InMemoryMemoryStore(memories)
    graph_store = _InMemoryGraphStore(memories)
    retriever = _retriever(memory_store, graph_store, "balanced")
    before = retriever.retrieve("Atlas planning note retrieval blockers", top_k=2)
    before_active = float(sum(not memory.decay.archived for memory in memory_store.list()))
    result = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"deduplication": DeduplicationDreamStrategy()},
    ).run_strategy("deduplication", at=datetime(2026, 4, 4, tzinfo=UTC))
    after = retriever.retrieve("Atlas planning note retrieval blockers", top_k=2)
    after_active = float(sum(not memory.decay.archived for memory in memory_store.list()))
    assert result is not None
    metrics = {
        "active_memories": after_active,
        "bundle_tokens": _token_cost(after.memories),
        "compression_ratio": round(after_active / before_active, 6),
    }
    baseline = {
        "active_memories": before_active,
        "bundle_tokens": _token_cost(before.memories),
    }
    return EvaluationCaseResult(
        case_id="performance-dedup",
        status="ok"
        if metrics["active_memories"] < baseline["active_memories"]
        and metrics["bundle_tokens"] < baseline["bundle_tokens"]
        else "failed",
        metrics=metrics,
        baseline_metrics=baseline,
        delta_metrics=_delta(metrics, baseline),
        notes={
            "archived_memory_ids": [
                memory.memory_id for memory in memory_store.list() if memory.decay.archived
            ]
        },
    )


def _suite_cases(suite: str) -> tuple[EvaluationCaseResult, ...]:
    if suite == "smoke":
        return (
            _run_ingest_case(),
            _run_retrieval_case(
                benchmark_index=0,
                corpus_name="project_memory",
                case_id="retrieval-project",
            ),
            _run_dream_case(),
        )

    if suite == "full":
        return (
            _run_ingest_case(),
            _run_retrieval_case(
                benchmark_index=0,
                corpus_name="project_memory",
                case_id="retrieval-project",
            ),
            _run_retrieval_case(
                benchmark_index=1,
                corpus_name="recency_trap",
                case_id="retrieval-recency",
            ),
            _run_dream_case(),
            _run_contradiction_case(),
            _run_performance_case(),
        )

    raise ValueError(f"Unknown eval suite: {suite}")


def write_report(report: EvaluationReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def run_evaluation_suite(suite: str, *, output_path: Path | None = None) -> EvaluationReport:
    cases = _suite_cases(suite)
    status = "ok" if all(case.status == "ok" for case in cases) else "failed"
    summary_metrics = {
        "case_count": float(len(cases)),
        "passed_case_count": float(sum(case.status == "ok" for case in cases)),
    }
    report = EvaluationReport(
        suite=suite,
        status=status,
        generated_at=datetime.now(UTC),
        cases=cases,
        summary_metrics=summary_metrics,
        output_path=str(output_path) if output_path is not None else None,
    )
    if output_path is not None:
        write_report(report, output_path)
    return report
