"""Milvus-backed vector store with shared vector-contract behavior."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _MissingMilvusDependencyError(RuntimeError):
    """Raised when Milvus dependencies are unavailable."""


class _MilvusRemoteSearchError(RuntimeError):
    """Raised when Milvus remote search fails unexpectedly."""


def _normalize_connection_and_collection(connection_string: str) -> tuple[str, str]:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)
    collection = query.get("collection", [parsed.path.strip("/")])[0].strip()
    if parsed.scheme:
        endpoint = f"{parsed.scheme}://{parsed.netloc}"
    else:
        endpoint = connection_string.split("?", 1)[0]
    return endpoint.rstrip("/"), collection or "cellin_vectors"


def _row_entities(hit: object) -> tuple[str, bool]:
    entity = getattr(hit, "entity", {})
    if isinstance(entity, dict):
        memory_id = str(entity.get("memory_id", getattr(hit, "id", ""))).strip()
        archived = bool(entity.get("archived", False))
        return memory_id, archived

    memory_id = str(getattr(hit, "memory_id", getattr(hit, "id", ""))).strip()
    return memory_id, bool(getattr(entity, "archived", False))


class _MilvusBackend:
    _VECTOR_DIMENSION = 12

    def __init__(self, connection_string: str) -> None:
        try:
            from pymilvus import (  # type: ignore[import-not-found]  # type: ignore[import-not-found]
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingMilvusDependencyError(
                "milvus backend requires optional dependency `pymilvus`"
            ) from exc

        self._endpoint, self._collection_name = _normalize_connection_and_collection(
            connection_string
        )
        self._collection_cls = Collection
        self._schema_cls = CollectionSchema
        self._field_schema_cls = FieldSchema
        self._data_type = DataType
        self._connections = connections
        self._utility = utility
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._tombstones: set[str] = set()
        self._initialized = False
        self._connect()
        self._ensure_collection_exists()

    def _connect(self) -> None:
        self._connections.connect(uri=self._endpoint)

    def _ensure_collection_exists(self) -> None:
        if self._initialized:
            return

        has_collection = getattr(self._utility, "has_collection", None)
        if callable(has_collection) and not has_collection(self._collection_name):
            schema = self._schema_cls(
                fields=(
                    self._field_schema_cls(
                        name="memory_id",
                        dtype=self._data_type.VARCHAR,
                        is_primary=True,
                        max_length=255,
                    ),
                    self._field_schema_cls(
                        name="vector",
                        dtype=self._data_type.FLOAT_VECTOR,
                        dim=self._VECTOR_DIMENSION,
                    ),
                    self._field_schema_cls(
                        name="archived",
                        dtype=self._data_type.BOOL,
                    ),
                )
            )
            self._collection_cls(self._collection_name, schema=schema)
        self._initialized = True

    def _collection(self) -> Any:
        return self._collection_cls(self._collection_name)

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        self._vectors[memory_id] = vector
        self._tombstones.discard(memory_id)
        self._collection().insert(
            [
                [memory_id],
                [list(vector)],
                [False],
            ]
        )

    def delete(self, memory_id: str) -> None:
        self._tombstones.add(memory_id)
        vector = self._vectors.get(memory_id, vectorize(memory_id))
        self._collection().insert(
            [
                [memory_id],
                [list(vector)],
                [True],
            ]
        )

    def _search_remote(self, query_vector: tuple[float, ...], limit: int) -> list[VectorMatch]:
        results: list[VectorMatch] = []
        collection = self._collection()
        try:
            matches = collection.search(
                data=[list(query_vector)],
                anns_field="vector",
                limit=limit,
                params={"metric_type": "COSINE"},
                expr="archived == false",
                output_fields=["memory_id", "archived"],
            )
            for hits in matches or []:
                if not isinstance(hits, Sequence):
                    continue
                for hit in hits:
                    memory_id, archived = _row_entities(hit)
                    if not memory_id or memory_id in self._tombstones or archived:
                        continue
                    score = float(getattr(hit, "score", 0.0))
                    results.append(
                        VectorMatch(memory_id=memory_id, score=round(max(score, 0.0), 6))
                    )
        except TypeError:
            pass
        except Exception as exc:
            raise _MilvusRemoteSearchError("milvus remote search failed") from exc
        return results

    def _search_local(self, query_vector: tuple[float, ...]) -> list[VectorMatch]:
        return [
            VectorMatch(
                memory_id=memory_id,
                score=round(cosine_similarity(query_vector, vector), 6),
            )
            for memory_id, vector in self._vectors.items()
            if memory_id not in self._tombstones
        ]

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        try:
            matches = self._search_remote(query_vector, limit)
        except _MilvusRemoteSearchError as exc:
            warnings.warn(f"{exc}", RuntimeWarning, stacklevel=2)
            matches = []
        if len(matches) < limit:
            existing = {result.memory_id for result in matches}
            for local in self._search_local(query_vector):
                if local.memory_id in existing:
                    continue
                matches.append(local)
                existing.add(local.memory_id)

        ordered = sorted(matches, key=lambda item: (-item.score, item.memory_id))
        return tuple(ordered[:limit])


_BACKENDS: dict[tuple[str, str], _MilvusBackend] = {}


def _backend_for(connection_string: str) -> _MilvusBackend:
    endpoint, collection_name = _normalize_connection_and_collection(connection_string)
    key = (endpoint, collection_name)
    backend = _BACKENDS.get(key)
    if backend is None:
        backend = _MilvusBackend(connection_string)
        _BACKENDS[key] = backend
    return backend


class MilvusVectorStore:
    """Milvus-backed vector index implementing shared vector operations."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _MilvusBackend | None = None,
    ) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        return self._backend.search(query, limit=limit)

    def delete(self, memory_id: str) -> None:
        self._backend.delete(memory_id)
