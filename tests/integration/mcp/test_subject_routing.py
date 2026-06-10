"""Integration tests for subject-scoped MCP storage routing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from cellin.core import Artifact, Modality, Provenance
from cellin.ingest.pipeline import CanonicalIngestor
from cellin.mcp import SubjectRegistry
from cellin.ranking.profiles import get_weight_profile
from cellin.ranking.weighted import WeightedRanker
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever

_NOW = datetime(2026, 6, 11, tzinfo=UTC)


def _artifact(artifact_id: str, text: str, *, topic: str) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        modality=Modality.TEXT,
        content=text,
        provenance=Provenance(source_id=artifact_id, source_type="fixture"),
        created_at=_NOW,
        metadata={"topic": topic},
    )


def _ingest_subject_memory(
    registry: SubjectRegistry,
    subject_id: str,
    *,
    artifact_id: str,
    text: str,
    topic: str,
) -> None:
    bundle = registry.get_or_create(subject_id)
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
        vector_store=bundle.vector_store,
        representation_store=bundle.representation_store,
    )
    ingestor.ingest((_artifact(artifact_id, text, topic=topic),))


def _retriever_for_subject(registry: SubjectRegistry, subject_id: str) -> WeightedRetriever:
    bundle = registry.get_or_create(subject_id)
    profile = replace(get_weight_profile("balanced"), candidate_limit=4, token_budget=100)
    return WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(
            memory_store=bundle.memory_store,
            graph_store=bundle.graph_store,
            vector_store=bundle.vector_store,
        ),
        ranker=WeightedRanker(profile=profile, now_provider=lambda: _NOW),
        profile=profile,
        memory_store=bundle.memory_store,
        representation_store=bundle.representation_store,
    )


def test_subject_routing_keeps_same_topic_isolated_across_subjects(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)
    _ingest_subject_memory(
        registry,
        "subject-a",
        artifact_id="artifact-a",
        text="Roadmap notes for the atlas launch sequence.",
        topic="launch-plan",
    )

    subject_a_bundle = registry.get_or_create("subject-a")
    subject_b_bundle = registry.get_or_create("subject-b")
    subject_b_retriever = _retriever_for_subject(registry, "subject-b")
    subject_b_results = subject_b_retriever.retrieve("atlas launch roadmap", top_k=5)

    assert len(subject_a_bundle.memory_store.list()) == 1
    assert subject_b_bundle.memory_store.list() == ()
    assert subject_b_bundle.graph_store.list_edges() == ()
    assert subject_b_results.memories == ()
