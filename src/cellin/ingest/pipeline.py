"""Canonical ingestion pipeline for Cellin."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from cellin.core import (
    Artifact,
    EdgeKind,
    GraphStore,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
)
from cellin.ingest.adapters import EnvelopeAdapter, built_in_adapters
from cellin.ingest.envelope import ArtifactEnvelope, IngestionBatchResult
from cellin.stores.vector_index import InMemoryVectorIndex


@dataclass(slots=True)
class CanonicalIngestor:
    """Turns normalized artifacts into persisted memory atoms and edges."""

    graph_store: GraphStore
    memory_store: MemoryStore
    vector_index: InMemoryVectorIndex
    adapters: Mapping[Modality, EnvelopeAdapter]

    @classmethod
    def with_built_in_adapters(
        cls,
        *,
        graph_store: GraphStore,
        memory_store: MemoryStore,
        vector_index: InMemoryVectorIndex,
    ) -> CanonicalIngestor:
        adapters = built_in_adapters()
        adapter_map = {
            Modality.TEXT: adapters[0],
            Modality.MARKDOWN: adapters[1],
            Modality.CHAT: adapters[2],
            Modality.JSON: adapters[3],
            Modality.IMAGE: adapters[4],
        }
        return cls(
            graph_store=graph_store,
            memory_store=memory_store,
            vector_index=vector_index,
            adapters=adapter_map,
        )

    def ingest(self, artifacts: Sequence[Artifact]) -> tuple[MemoryAtom, ...]:
        """Persist a sequence of normalized artifacts as memory atoms."""

        memories = tuple(self._artifact_to_memory(artifact) for artifact in artifacts)
        self._persist_memories(memories)
        for memory in memories:
            self.vector_index.upsert(memory.memory_id, memory.text)
        return memories

    def ingest_envelopes(self, envelopes: Sequence[ArtifactEnvelope]) -> IngestionBatchResult:
        artifacts = tuple(self._normalize_envelope(envelope) for envelope in envelopes)
        memories = self.ingest(artifacts)
        edges = self._build_edges(artifacts, memories)
        self._persist_edges(edges)
        return IngestionBatchResult(artifacts=artifacts, memories=memories, edges=edges)

    def _persist_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        put_many = getattr(self.memory_store, "put_many", None)
        if callable(put_many):
            put_many(memories)
        else:
            for memory in memories:
                self.memory_store.put(memory)

        if not self._graph_requires_memory_upserts():
            return

        upsert_memories = getattr(self.graph_store, "upsert_memories", None)
        if callable(upsert_memories):
            upsert_memories(memories)
            return

        for memory in memories:
            self.graph_store.upsert_memory(memory)

    def _persist_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        upsert_edges = getattr(self.graph_store, "upsert_edges", None)
        if callable(upsert_edges):
            upsert_edges(edges)
            return

        for edge in edges:
            self.graph_store.upsert_edge(edge)

    def _graph_requires_memory_upserts(self) -> bool:
        shares_memory_store = getattr(self.graph_store, "shares_memory_store", None)
        if callable(shares_memory_store):
            return not bool(shares_memory_store(self.memory_store))
        return True

    def _normalize_envelope(self, envelope: ArtifactEnvelope) -> Artifact:
        adapter = self.adapters[envelope.modality]
        return adapter.normalize(envelope)

    def _artifact_to_memory(self, artifact: Artifact) -> MemoryAtom:
        return MemoryAtom(
            memory_id=artifact.artifact_id,
            kind=MemoryKind.ATOM,
            text=artifact.content,
            provenance=artifact.provenance,
            modality=artifact.modality,
            created_at=artifact.created_at,
            observed_at=artifact.observed_at,
            artifact_id=artifact.artifact_id,
            salience_score=artifact.salience_score,
            trust_score=artifact.trust_score,
            metadata=artifact.metadata,
        )

    def _build_edges(
        self,
        artifacts: Sequence[Artifact],
        memories: Sequence[MemoryAtom],
    ) -> tuple[MemoryEdge, ...]:
        edges: list[MemoryEdge] = []
        last_by_topic: dict[str, str] = {}
        last_by_conversation: dict[str, str] = {}

        for artifact, memory in zip(artifacts, memories, strict=True):
            topic = artifact.metadata.get("topic")
            if isinstance(topic, str):
                previous = last_by_topic.get(topic)
                if previous is not None:
                    edges.append(
                        self._edge(
                            source_id=previous,
                            target_id=memory.memory_id,
                            kind=EdgeKind.SUPPORTS,
                            observed_at=artifact.created_at,
                            source_ref=artifact.artifact_id,
                            label=topic,
                        )
                    )
                last_by_topic[topic] = memory.memory_id

            conversation_id = artifact.metadata.get("conversation_id")
            if isinstance(conversation_id, str):
                previous = last_by_conversation.get(conversation_id)
                if previous is not None:
                    edges.append(
                        self._edge(
                            source_id=previous,
                            target_id=memory.memory_id,
                            kind=EdgeKind.ABOUT,
                            observed_at=artifact.created_at,
                            source_ref=artifact.artifact_id,
                            label=conversation_id,
                        )
                    )
                last_by_conversation[conversation_id] = memory.memory_id

        return tuple(edges)

    def _edge(
        self,
        *,
        source_id: str,
        target_id: str,
        kind: EdgeKind,
        observed_at: datetime,
        source_ref: str,
        label: str,
    ) -> MemoryEdge:
        return MemoryEdge(
            edge_id=f"{kind.value}:{source_id}:{target_id}",
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            provenance=Provenance(source_id=source_ref, source_type="ingest-link"),
            created_at=observed_at,
            metadata={"label": label},
        )
