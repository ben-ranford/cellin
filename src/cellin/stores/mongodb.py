"""MongoDB-backed memory and graph stores for Cellin."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast
from urllib.parse import urlparse

from cellin.core import MemoryAtom, MemoryEdge, MemoryStore
from cellin.stores._graph_serialization import (
    edge_is_archived,
    edge_payload,
    load_edge_payload,
    load_memory_payload,
    memory_payload,
)


class _MissingMongoDependencyError(RuntimeError):
    """Raised when MongoDB dependencies are unavailable."""


def _as_mapping(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("MongoDB documents must decode to mappings")
    return {str(key): value for key, value in raw.items()}


def _normalize_memory_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    document = dict(raw)
    document["memory_id"] = document.get("memory_id", document.get("_id"))
    return document


def _normalize_edge_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    document = dict(raw)
    document["edge_id"] = document.get("edge_id", document.get("_id"))
    return document


def _sorted_documents(rows: Iterable[object]) -> list[dict[str, Any]]:
    documents = [_as_mapping(row) for row in rows]
    return sorted(
        (dict(document) for document in documents),
        key=lambda document: str(document.get("_id", "")),
    )


def _database_name(connection_string: str) -> str:
    parsed = urlparse(connection_string)
    database = parsed.path.strip("/")
    return database or "cellin"


class _MongoBackend:
    """Low-level MongoDB collection access shared by memory and graph roles."""

    def __init__(self, connection_string: str) -> None:
        try:
            import pymongo  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingMongoDependencyError(
                "mongodb backend requires optional dependency `pymongo`"
            ) from exc

        client = pymongo.MongoClient(connection_string)
        database = client[_database_name(connection_string)]
        self._memory_collection = database["cellin_memories"]
        self._edge_collection = database["cellin_edges"]

    def put_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        if not memories:
            return

        for memory in memories:
            payload = cast(dict[str, Any], memory_payload(memory))
            payload["_id"] = memory.memory_id
            self._memory_collection.update_one(
                {"_id": memory.memory_id},
                {"$set": payload},
                upsert=True,
            )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        raw = self._memory_collection.find_one({"_id": memory_id})
        if raw is None:
            return None
        return load_memory_payload(_normalize_memory_document(_as_mapping(raw)))

    def list_memories(self) -> tuple[MemoryAtom, ...]:
        return tuple(
            load_memory_payload(_normalize_memory_document(document))
            for document in _sorted_documents(self._memory_collection.find())
        )

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        if not edges:
            return

        for edge in edges:
            payload = cast(dict[str, Any], edge_payload(edge))
            payload["_id"] = edge.edge_id
            self._edge_collection.update_one(
                {"_id": edge.edge_id},
                {"$set": payload},
                upsert=True,
            )

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        rows = self._edge_collection.find(
            {"$or": [{"source_id": memory_id}, {"target_id": memory_id}]}
        )
        edges = [
            load_edge_payload(_normalize_edge_document(document))
            for document in _sorted_documents(rows)
        ]
        return tuple(edge for edge in edges if not edge_is_archived(edge))

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        edges = [
            load_edge_payload(_normalize_edge_document(document))
            for document in _sorted_documents(self._edge_collection.find())
        ]
        return tuple(edge for edge in edges if not edge_is_archived(edge))


_BACKENDS: dict[str, _MongoBackend] = {}


def _backend_for(connection_string: str) -> _MongoBackend:
    backend = _BACKENDS.get(connection_string)
    if backend is None:
        backend = _MongoBackend(connection_string)
        _BACKENDS[connection_string] = backend
    return backend


class MongoDBMemoryStore:
    """Persist memory atoms as MongoDB documents keyed by `memory_id`."""

    def __init__(self, connection_string: str, *, _backend: _MongoBackend | None = None) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class MongoDBGraphStore:
    """Persist graph edges and supporting memory records in MongoDB."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _MongoBackend | None = None,
    ) -> None:
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
        return (
            isinstance(memory_store, MongoDBMemoryStore) and memory_store._backend is self._backend
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
