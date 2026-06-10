"""Integration tests for the canonical ingestion pipeline and local stores."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote

from cellin.core import Artifact, MemoryAtom, MemoryEdge, Modality, Provenance
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore
from cellin.stores import sqlite as sqlite_module


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


def _build_envelope(
    envelope_id: str,
    *,
    observed_at: datetime,
    topic: str,
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        envelope_id=envelope_id,
        modality=Modality.TEXT,
        payload=envelope_id,
        source_id=f"source-{envelope_id}",
        source_type="fixture",
        observed_at=observed_at,
        metadata={"topic": topic},
    )


def _artifact(artifact_id: str, *, observed_at: datetime, topic: str) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        modality=Modality.TEXT,
        content=f"{artifact_id} content",
        provenance=Provenance(source_id=artifact_id, source_type="fixture"),
        created_at=observed_at,
        observed_at=observed_at,
        metadata={"topic": topic},
    )


def test_ingestion_pipeline_persists_memories_edges_and_vectors(tmp_path) -> None:
    database_path = tmp_path / "cellin.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    memory_store = SQLiteMemoryStore(str(database_path))
    vector_index = InMemoryVectorIndex()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_store=vector_index,
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

    vector_results = vector_index.search("stores memory atoms in a graph", limit=2)
    assert vector_results[0].memory_id == "text-1"
    assert vector_results[0].score > 0.0

    neighbors = graph_store.neighbors("text-1")
    assert neighbors
    assert neighbors[0].metadata["label"] == "atlas"


def test_ingestion_pipeline_batches_sqlite_writes_for_shared_store(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "cellin.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    memory_store = SQLiteMemoryStore(str(database_path))
    vector_index = InMemoryVectorIndex()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_store=vector_index,
    )
    connect_calls = 0
    original_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite_module.sqlite3, "connect", counting_connect)

    result = ingestor.ingest_envelopes(_load_fixture())

    assert len(result.memories) == 4
    assert connect_calls == 2


def test_ingestion_pipeline_uses_collision_safe_sqlite_edge_ids(tmp_path) -> None:
    database_path = tmp_path / "cellin.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    memory_store = SQLiteMemoryStore(str(database_path))
    vector_index = InMemoryVectorIndex()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_store=vector_index,
    )
    observed_at = datetime(2026, 4, 5, tzinfo=UTC)

    result = ingestor.ingest_envelopes(
        (
            _build_envelope("a:b", observed_at=observed_at, topic="topic-a"),
            _build_envelope("c", observed_at=observed_at, topic="topic-a"),
            _build_envelope("a", observed_at=observed_at, topic="topic-b"),
            _build_envelope("b:c", observed_at=observed_at, topic="topic-b"),
        )
    )

    edges = graph_store.list_edges()
    assert len(result.edges) == 2
    assert len(edges) == 2
    assert {(edge.source_id, edge.target_id) for edge in edges} == {("a:b", "c"), ("a", "b:c")}
    assert {edge.edge_id for edge in edges} == {
        f"supports:{quote('a:b', safe='')}:{quote('c', safe='')}",
        f"supports:{quote('a', safe='')}:{quote('b:c', safe='')}",
    }


def test_ingestion_pipeline_avoids_duplicate_graph_memory_writes_for_shared_backends() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)

    class _CountingMemoryStore:
        def __init__(self) -> None:
            self._memories: dict[str, MemoryAtom] = {}
            self.put_many_calls = 0

        def put(self, memory: MemoryAtom) -> None:
            self.put_many((memory,))

        def put_many(self, memories: tuple[MemoryAtom, ...]) -> None:
            self.put_many_calls += 1
            for memory in memories:
                self._memories[memory.memory_id] = memory

        def get(self, memory_id: str) -> MemoryAtom | None:
            return self._memories.get(memory_id)

        def list(self) -> tuple[MemoryAtom, ...]:
            return tuple(self._memories.values())

    class _CountingGraphStore:
        def __init__(self, *, shared: bool) -> None:
            self._shared = shared
            self.memory_upsert_calls = 0

        def upsert_memory(self, memory: MemoryAtom) -> None:
            del memory
            self.memory_upsert_calls += 1

        def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
            self.memory_upsert_calls += len(memories)

        def upsert_edge(self, edge: MemoryEdge) -> None:
            del edge

        def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
            del edges

        def get_memory(self, memory_id: str) -> MemoryAtom | None:
            del memory_id
            return None

        def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
            del memory_id
            return ()

        def list_edges(self) -> tuple[MemoryEdge, ...]:
            return ()

        def shares_memory_store(self, memory_store: _CountingMemoryStore) -> bool:
            del memory_store
            return self._shared

    shared_memory_store = _CountingMemoryStore()
    shared_graph_store = _CountingGraphStore(shared=True)
    separate_memory_store = _CountingMemoryStore()
    separate_graph_store = _CountingGraphStore(shared=False)
    shared_ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=shared_graph_store,
        memory_store=shared_memory_store,
        vector_store=InMemoryVectorIndex(),
    )
    separate_ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=separate_graph_store,
        memory_store=separate_memory_store,
        vector_store=InMemoryVectorIndex(),
    )
    artifacts = (
        _artifact("atlas-1", observed_at=now, topic="atlas"),
        _artifact("atlas-2", observed_at=now, topic="atlas"),
    )

    shared_memories = shared_ingestor.ingest(artifacts)
    separate_memories = separate_ingestor.ingest(artifacts)

    assert len(shared_memories) == 2
    assert len(separate_memories) == 2
    assert shared_memory_store.put_many_calls == 1
    assert separate_memory_store.put_many_calls == 1
    assert shared_graph_store.memory_upsert_calls == 0
    assert separate_graph_store.memory_upsert_calls == 2
