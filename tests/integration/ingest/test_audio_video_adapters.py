"""Tests for AudioAdapter, VideoAdapter, UnsupportedModalityError, and CAUSED_BY edge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from cellin.core import (
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    Modality,
)
from cellin.ingest import (
    ArtifactEnvelope,
    AudioAdapter,
    CanonicalIngestor,
    UnsupportedModalityError,
    VideoAdapter,
)
from cellin.stores import InMemoryVectorIndex

_NOW = datetime(2026, 4, 22, tzinfo=UTC)


def _envelope(
    envelope_id: str,
    modality: Modality,
    payload: object,
    *,
    metadata: dict[str, object] | None = None,
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        envelope_id=envelope_id,
        modality=modality,
        payload=payload,
        source_id=f"source-{envelope_id}",
        source_type="fixture",
        observed_at=_NOW,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# AudioAdapter
# ---------------------------------------------------------------------------


def test_audio_adapter_supports_audio_modality() -> None:
    assert AudioAdapter().supports(Modality.AUDIO) is True
    assert AudioAdapter().supports(Modality.VIDEO) is False


def test_audio_adapter_with_provider_returns_artifact() -> None:
    adapter = AudioAdapter(transcript_provider=lambda data: f"transcript:{len(data)}")
    artifact = adapter.normalize(_envelope("audio-1", Modality.AUDIO, {"data": b"\x00\x01\x02"}))
    assert artifact.content == "transcript:3"
    assert artifact.artifact_id == "audio-1"


def test_audio_adapter_stub_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="transcript_provider"):
        AudioAdapter().normalize(_envelope("audio-1", Modality.AUDIO, {"data": b""}))


def test_audio_adapter_rejects_non_dict_payload() -> None:
    adapter = AudioAdapter(transcript_provider=lambda _: "t")
    with pytest.raises(TypeError, match="AudioAdapter"):
        adapter.normalize(_envelope("audio-bad", Modality.AUDIO, "not-a-dict"))


# ---------------------------------------------------------------------------
# VideoAdapter
# ---------------------------------------------------------------------------


def test_video_adapter_supports_video_modality() -> None:
    assert VideoAdapter().supports(Modality.VIDEO) is True
    assert VideoAdapter().supports(Modality.AUDIO) is False


def test_video_adapter_with_provider_returns_artifact() -> None:
    adapter = VideoAdapter(caption_provider=lambda data: f"caption:{len(data)}")
    artifact = adapter.normalize(_envelope("video-1", Modality.VIDEO, {"data": b"\xff\xfe"}))
    assert artifact.content == "caption:2"
    assert artifact.artifact_id == "video-1"


def test_video_adapter_stub_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="caption_provider"):
        VideoAdapter().normalize(_envelope("video-1", Modality.VIDEO, {"data": b""}))


def test_video_adapter_rejects_non_dict_payload() -> None:
    adapter = VideoAdapter(caption_provider=lambda _: "c")
    with pytest.raises(TypeError, match="VideoAdapter"):
        adapter.normalize(_envelope("video-bad", Modality.VIDEO, ["not-a-dict"]))


# ---------------------------------------------------------------------------
# UnsupportedModalityError via pipeline
# ---------------------------------------------------------------------------


@dataclass
class _MinimalMemoryStore:
    memories: dict[str, MemoryAtom]

    def __init__(self) -> None:
        self.memories = {}

    def put(self, memory: MemoryAtom) -> None:
        self.memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self.memories.values())


@dataclass
class _MinimalGraphStore(GraphStore):
    edges: list[MemoryEdge]
    memories: dict[str, MemoryAtom]

    def __init__(self) -> None:
        self.edges = []
        self.memories = {}

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self.memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.edges.append(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(e for e in self.edges if e.source_id == memory_id or e.target_id == memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self.edges)


def _build_ingestor() -> CanonicalIngestor:
    import os
    import tempfile

    from cellin.stores import SQLiteGraphStore, SQLiteMemoryStore

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.sqlite")
    return CanonicalIngestor.with_built_in_adapters(
        graph_store=SQLiteGraphStore(db),
        memory_store=SQLiteMemoryStore(db),
        vector_store=InMemoryVectorIndex(),
    )


def test_unsupported_modality_error_raised_for_unknown_modality(tmp_path) -> None:
    from cellin.stores import SQLiteGraphStore, SQLiteMemoryStore

    db = str(tmp_path / "test.sqlite")
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=SQLiteGraphStore(db),
        memory_store=SQLiteMemoryStore(db),
        vector_store=InMemoryVectorIndex(),
    )
    # Remove audio from the adapter map to simulate unknown modality
    del ingestor.adapters[Modality.AUDIO]

    with pytest.raises(UnsupportedModalityError) as exc_info:
        ingestor.ingest_envelopes((_envelope("audio-x", Modality.AUDIO, {"data": b""}),))
    assert exc_info.value.modality is Modality.AUDIO


# ---------------------------------------------------------------------------
# CAUSED_BY edge emission during ingest
# ---------------------------------------------------------------------------


def test_ingest_emits_caused_by_edge_when_metadata_present(tmp_path) -> None:
    from cellin.stores import SQLiteGraphStore, SQLiteMemoryStore

    db = str(tmp_path / "test.sqlite")
    graph_store = SQLiteGraphStore(db)
    memory_store = SQLiteMemoryStore(db)
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_store=InMemoryVectorIndex(),
    )

    result = ingestor.ingest_envelopes(
        (
            _envelope(
                "new-memory-1",
                Modality.TEXT,
                "A consequence of event X",
                metadata={"caused_by": "prior-memory-99"},
            ),
        )
    )

    caused_by_edges = [e for e in result.edges if e.kind is EdgeKind.CAUSED_BY]
    assert len(caused_by_edges) == 1
    edge = caused_by_edges[0]
    assert edge.source_id == "new-memory-1"
    assert edge.target_id == "prior-memory-99"


def test_ingest_without_caused_by_emits_no_caused_by_edge(tmp_path) -> None:
    from cellin.stores import SQLiteGraphStore, SQLiteMemoryStore

    db = str(tmp_path / "test.sqlite")
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=SQLiteGraphStore(db),
        memory_store=SQLiteMemoryStore(db),
        vector_store=InMemoryVectorIndex(),
    )

    result = ingestor.ingest_envelopes((_envelope("no-cause", Modality.TEXT, "plain text"),))

    assert not any(e.kind is EdgeKind.CAUSED_BY for e in result.edges)
