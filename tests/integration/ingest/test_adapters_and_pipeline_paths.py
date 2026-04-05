"""Additional ingest coverage for adapter and pipeline branch behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cellin.core import (
    Artifact,
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryStore,
    Modality,
)
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.ingest.adapters import (
    ChatAdapter,
    ImageAdapter,
    JSONAdapter,
    MarkdownAdapter,
    TextAdapter,
)
from cellin.stores import InMemoryVectorIndex


def _envelope(
    envelope_id: str,
    modality: Modality,
    payload: object,
    *,
    observed_at: datetime,
    metadata: dict[str, object] | None = None,
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        envelope_id=envelope_id,
        modality=modality,
        payload=payload,
        source_id=f"source-{envelope_id}",
        source_type="fixture",
        observed_at=observed_at,
        metadata=metadata or {},
    )


@dataclass
class PutOnlyMemoryStore(MemoryStore):
    memories: dict[str, MemoryAtom]
    put_calls: list[str]

    def __init__(self) -> None:
        self.memories = {}
        self.put_calls = []

    def put(self, memory: MemoryAtom) -> None:
        self.put_calls.append(memory.memory_id)
        self.memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self.memories.values())


@dataclass
class LoopGraphStore(GraphStore):
    memories: dict[str, MemoryAtom]
    edges: list[MemoryEdge]
    upserted_memory_ids: list[str]
    upserted_edge_ids: list[str]

    def __init__(self) -> None:
        self.memories = {}
        self.edges = []
        self.upserted_memory_ids = []
        self.upserted_edge_ids = []

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self.upserted_memory_ids.append(memory.memory_id)
        self.memories[memory.memory_id] = memory

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.upserted_edge_ids.append(edge.edge_id)
        self.edges.append(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self.memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.source_id == memory_id or edge.target_id == memory_id
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self.edges)


class BatchGraphStore(LoopGraphStore):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[tuple[str, ...]] = []

    def shares_memory_store(self, _: MemoryStore) -> bool:
        return False

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        self.batches.append(tuple(memory.memory_id for memory in memories))
        for memory in memories:
            self.upsert_memory(memory)


def test_adapters_cover_supported_modalities_and_normalization_paths() -> None:
    observed_at = datetime(2026, 4, 5, tzinfo=UTC)
    text_adapter = TextAdapter()
    markdown_adapter = MarkdownAdapter()
    json_adapter = JSONAdapter()
    chat_adapter = ChatAdapter()
    image_adapter = ImageAdapter(text_provider=lambda _: "provided image text")

    assert text_adapter.supports(Modality.TEXT) is True
    assert markdown_adapter.supports(Modality.MARKDOWN) is True
    assert json_adapter.supports(Modality.JSON) is True
    assert chat_adapter.supports(Modality.CHAT) is True
    assert image_adapter.supports(Modality.IMAGE) is True

    assert (
        markdown_adapter.normalize(
            _envelope("markdown-1", Modality.MARKDOWN, "# Atlas", observed_at=observed_at)
        ).content
        == "# Atlas"
    )
    assert (
        json_adapter.normalize(
            _envelope(
                "json-1",
                Modality.JSON,
                {"topic": "atlas", "status": "green"},
                observed_at=observed_at,
            )
        ).content
        == '{"status": "green", "topic": "atlas"}'
    )

    chat_artifact = chat_adapter.normalize(
        _envelope(
            "chat-1",
            Modality.CHAT,
            {
                "conversation_id": "conv-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
            observed_at=observed_at,
        )
    )
    assert chat_artifact.content == "user: hello"
    assert chat_artifact.metadata["conversation_id"] == "conv-1"

    image_artifact = image_adapter.normalize(
        _envelope(
            "image-1",
            Modality.IMAGE,
            {"path": "board.png", "caption": "board"},
            observed_at=observed_at,
        )
    )
    assert image_artifact.content == "provided image text"
    assert image_artifact.metadata["image_path"] == "board.png"


def test_ingestor_falls_back_to_put_and_upsert_loops_for_simple_stores() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    memory_store = PutOnlyMemoryStore()
    graph_store = LoopGraphStore()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_index=InMemoryVectorIndex(),
    )
    envelopes = (
        _envelope(
            "chat-1",
            Modality.CHAT,
            {
                "conversation_id": "conv-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
            observed_at=now,
        ),
        _envelope(
            "chat-2",
            Modality.CHAT,
            {
                "conversation_id": "conv-1",
                "messages": [{"role": "assistant", "content": "world"}],
            },
            observed_at=now + timedelta(minutes=1),
        ),
    )

    result = ingestor.ingest_envelopes(envelopes)

    assert tuple(memory_store.put_calls) == ("chat-1", "chat-2")
    assert tuple(graph_store.upserted_memory_ids) == ("chat-1", "chat-2")
    assert tuple(graph_store.upserted_edge_ids) == ("about:chat-1:chat-2",)
    assert len(result.edges) == 1
    assert result.edges[0].kind is EdgeKind.ABOUT


def test_ingestor_uses_graph_batch_memory_upserts_when_available() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    memory_store = PutOnlyMemoryStore()
    graph_store = BatchGraphStore()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=graph_store,
        memory_store=memory_store,
        vector_index=InMemoryVectorIndex(),
    )
    artifact = Artifact(
        artifact_id="text-1",
        modality=Modality.TEXT,
        content="Atlas text artifact",
        provenance=None,  # type: ignore[arg-type]
        created_at=now,
        observed_at=now,
    )
    artifact.provenance = (
        ingestor.adapters[Modality.TEXT]
        .normalize(  # type: ignore[assignment]
            _envelope("text-1", Modality.TEXT, "Atlas text artifact", observed_at=now)
        )
        .provenance
    )

    memories = ingestor.ingest((artifact,))

    assert tuple(memory.memory_id for memory in memories) == ("text-1",)
    assert graph_store.batches == [("text-1",)]
