"""Redis-backed memory and graph stores for Cellin."""

from __future__ import annotations

from urllib.parse import urlparse

from cellin.core import MemoryAtom, MemoryEdge, MemoryStore
from cellin.stores._graph_serialization import (
    dump_edge,
    dump_memory,
    edge_is_archived,
    load_edge,
    load_memory,
)


class _MissingRedisDependencyError(RuntimeError):
    """Raised when Redis dependencies are unavailable."""


def _redis_namespace(connection_string: str) -> str:
    parsed = urlparse(connection_string)
    database = parsed.path.strip("/") or "0"
    return f"cellin:{database}"


class _RedisBackend:
    """Low-level Redis access shared between memory and graph roles."""

    def __init__(self, connection_string: str) -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingRedisDependencyError(
                "redis backend requires optional dependency `redis`"
            ) from exc

        self._client = redis.Redis.from_url(connection_string, decode_responses=True)
        self._namespace = _redis_namespace(connection_string)

    def _memory_key(self, memory_id: str) -> str:
        return f"{self._namespace}:memory:{memory_id}"

    def _edge_key(self, edge_id: str) -> str:
        return f"{self._namespace}:edge:{edge_id}"

    def _edge_by_src_key(self, memory_id: str) -> str:
        return f"{self._namespace}:edge-by-src:{memory_id}"

    def _edge_by_tgt_key(self, memory_id: str) -> str:
        return f"{self._namespace}:edge-by-tgt:{memory_id}"

    def put_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        for memory in memories:
            self._client.set(self._memory_key(memory.memory_id), dump_memory(memory))

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        payload = self._client.get(self._memory_key(memory_id))
        if payload is None:
            return None
        return load_memory(str(payload))

    def list_memories(self) -> tuple[MemoryAtom, ...]:
        keys = sorted(str(key) for key in self._client.scan_iter(f"{self._namespace}:memory:*"))
        return tuple(
            load_memory(str(payload))
            for key in keys
            if (payload := self._client.get(key)) is not None
        )

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        for edge in edges:
            self._client.set(self._edge_key(edge.edge_id), dump_edge(edge))
            self._client.sadd(self._edge_by_src_key(edge.source_id), edge.edge_id)
            self._client.sadd(self._edge_by_tgt_key(edge.target_id), edge.edge_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        src_ids = self._client.smembers(self._edge_by_src_key(memory_id))
        tgt_ids = self._client.smembers(self._edge_by_tgt_key(memory_id))
        all_ids = src_ids | tgt_ids
        edges = []
        for edge_id in sorted(all_ids):
            payload = self._client.get(self._edge_key(str(edge_id)))
            if payload is None:
                continue
            edge = load_edge(str(payload))
            if edge_is_archived(edge):
                continue
            edges.append(edge)
        return tuple(edges)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        edges = []
        for key in sorted(str(key) for key in self._client.scan_iter(f"{self._namespace}:edge:*")):
            payload = self._client.get(key)
            if payload is None:
                continue
            edge = load_edge(str(payload))
            if not edge_is_archived(edge):
                edges.append(edge)
        return tuple(edges)


_BACKENDS: dict[str, _RedisBackend] = {}


def _backend_for(connection_string: str) -> _RedisBackend:
    backend = _BACKENDS.get(connection_string)
    if backend is None:
        backend = _RedisBackend(connection_string)
        _BACKENDS[connection_string] = backend
    return backend


class RedisMemoryStore:
    """Persist memory atoms in Redis using JSON payloads."""

    def __init__(self, connection_string: str, *, _backend: _RedisBackend | None = None) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class RedisGraphStore:
    """Persist graph edges and supporting memories in Redis."""

    def __init__(self, connection_string: str, *, _backend: _RedisBackend | None = None) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.upsert_edges((edge,))

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return isinstance(memory_store, RedisMemoryStore) and memory_store._backend is self._backend

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
