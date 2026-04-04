"""Integration tests for the canonical ingestion pipeline and local stores."""

from __future__ import annotations

import json
from datetime import datetime

from cellin.core import Modality
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore


def _load_fixture() -> tuple[ArtifactEnvelope, ...]:
    with open("evals/fixtures/ingest/sample_dataset.json", encoding="utf-8") as handle:
        raw_dataset = json.load(handle)

    return tuple(
        ArtifactEnvelope(
            envelope_id=item["envelope_id"],
            modality=Modality(item["modality"]),
            payload=item["payload"],
            source_id=item["source_id"],
            source_type=item["source_type"],
            observed_at=datetime.fromisoformat(item["observed_at"]),
            metadata=item["metadata"],
        )
        for item in raw_dataset
    )


def test_ingestion_pipeline_persists_memories_edges_and_vectors(tmp_path) -> None:
    database_path = tmp_path / "cellin.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    memory_store = SQLiteMemoryStore(str(database_path))
    vector_index = InMemoryVectorIndex()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_index=vector_index,
    )

    result = ingestor.ingest_envelopes(_load_fixture())

    assert len(result.artifacts) == 4
    assert len(result.memories) == 4
    assert len(result.edges) >= 2

    markdown_memory = memory_store.get("markdown-1")
    assert markdown_memory is not None
    assert markdown_memory.artifact_id == "markdown-1"
    assert markdown_memory.metadata["topic"] == "atlas"

    image_memory = memory_store.get("image-1")
    assert image_memory is not None
    assert "Whiteboard sketch" in image_memory.text
    assert "memory graph sketch" in image_memory.text

    vector_results = vector_index.search("atlas memory graph", limit=2)
    assert vector_results[0].memory_id in {"text-1", "image-1"}

    neighbors = graph_store.neighbors("text-1")
    assert neighbors
    assert neighbors[0].metadata["label"] == "atlas"
