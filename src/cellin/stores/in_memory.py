"""In-memory runtime stores for memory and graph state."""

from __future__ import annotations

from collections.abc import Sequence

from cellin.core import MemoryAtom, MemoryEdge, MemoryStore


def _edge_archived(edge: MemoryEdge) -> bool:
    archived = edge.metadata.get("archived")
    return bool(archived) if isinstance(archived, bool) else False


class InMemoryMemoryStore:
    """In-memory memory store used by default CLI and eval runtime presets."""

    def __init__(self, memories: Sequence[MemoryAtom] = ()) -> None:
        self._memories: dict[str, MemoryAtom] = {}
        self.put_many(tuple(memories))

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: Sequence[MemoryAtom]) -> None:
        for memory in memories:
            self._memories[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return tuple(self._memories.values())


class InMemoryGraphStore:
    """In-memory graph store used by default CLI and eval runtime presets."""

    def __init__(
        self,
        memories: Sequence[MemoryAtom] = (),
        edges: Sequence[MemoryEdge] = (),
    ) -> None:
        self._memory_store: MemoryStore | None = None
        self._memories: dict[str, MemoryAtom] = {}
        self._edges: dict[str, MemoryEdge] = {}
        self.upsert_memories(tuple(memories))
        self.upsert_edges(tuple(edges))

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memories[memory.memory_id] = memory

    def upsert_memories(self, memories: Sequence[MemoryAtom]) -> None:
        for memory in memories:
            self.upsert_memory(memory)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._edges[edge.edge_id] = edge

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        for edge in edges:
            self.upsert_edge(edge)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return self._memory_store is memory_store

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._memories.get(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for edge in self._edges.values()
            if edge.source_id == memory_id or edge.target_id == memory_id
            if not _edge_archived(edge)
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(edge for edge in self._edges.values() if not _edge_archived(edge))
