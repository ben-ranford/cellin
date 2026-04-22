"""Shared store-layer utilities for memory filtering and delegation base classes."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from cellin.core import GraphStore, MemoryAtom, MemoryEdge, MemoryStore


def filter_memories(
    memories: Iterable[MemoryAtom],
    *,
    archived: bool | None = None,
    topic: str | None = None,
) -> Sequence[MemoryAtom]:
    result: list[MemoryAtom] = []
    for memory in memories:
        if archived is not None and memory.decay.archived != archived:
            continue
        if topic is not None and memory.metadata.get("topic") != topic:
            continue
        result.append(memory)
    return result


class _MemoryBackend(Protocol):
    def put_memories(self, memories: Sequence[MemoryAtom]) -> None: ...
    def get_memory(self, memory_id: str) -> MemoryAtom | None: ...
    def list_memories(self) -> tuple[MemoryAtom, ...]: ...


class _GraphBackend(Protocol):
    def put_memories(self, memories: Sequence[MemoryAtom]) -> None: ...
    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None: ...
    def get_memory(self, memory_id: str) -> MemoryAtom | None: ...
    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]: ...
    def list_edges(self) -> tuple[MemoryEdge, ...]: ...


class _DelegatingMemoryStore(MemoryStore):
    """Concrete base for memory stores that fully delegate to `self._backend`."""

    _backend: _MemoryBackend

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()

    def list_by(
        self,
        *,
        archived: bool | None = None,
        topic: str | None = None,
    ) -> Sequence[MemoryAtom]:
        return filter_memories(self._backend.list_memories(), archived=archived, topic=topic)


class _DelegatingGraphStore(GraphStore):
    """Concrete base for graph stores that fully delegate to `self._backend`."""

    _backend: _GraphBackend

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.upsert_edges((edge,))

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return getattr(memory_store, "_backend", None) is self._backend

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
