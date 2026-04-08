"""Qdrant-backed vector store with shared vector-contract behavior."""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _MissingQdrantDependencyError(RuntimeError):
    """Raised when Qdrant dependencies are unavailable."""


class _QdrantRemoteQueryError(RuntimeError):
    """Raised when qdrant remote query fails unexpectedly."""


def _normalize_connection_and_collection(connection_string: str) -> tuple[str, str]:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)

    collection = query.get("collection", [parsed.path.strip("/")])[0].strip()

    if parsed.scheme:
        endpoint = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    else:
        endpoint = connection_string.split("?", 1)[0]

    return endpoint.rstrip("/"), collection or "cellin_vectors"


def _coerce_vector(value: object) -> tuple[float, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray)):
        return ()

    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return ()


def _extract_payload(point: object) -> Mapping[str, Any]:
    payload = getattr(point, "payload", None)
    if isinstance(payload, Mapping):
        return payload
    if isinstance(point, Mapping):
        return point
    return {}


class _QdrantBackend:
    _VECTOR_DIMENSION = 12

    def __init__(self, connection_string: str) -> None:
        try:
            import qdrant_client  # type: ignore[import-not-found]
            from qdrant_client.http import models  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingQdrantDependencyError(
                "qdrant backend requires optional dependency `qdrant-client`"
            ) from exc

        self._endpoint, self._collection_name = _normalize_connection_and_collection(
            connection_string
        )
        if self._endpoint:
            self._client = qdrant_client.QdrantClient(url=self._endpoint)
        else:
            self._client = qdrant_client.QdrantClient()
        self._models = models
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._tombstones: set[str] = set()
        self._initialized = False
        self._ensure_collection_exists()

    def _vector_payload(
        self, memory_id: str, vector: tuple[float, ...], *, archived: bool
    ) -> dict[str, Any]:
        return {"memory_id": memory_id, "archived": archived, "vector": list(vector)}

    def _list_collections(self) -> set[str]:
        response = self._client.get_collections()
        return {
            str(collection.name)
            for collection in getattr(response, "collections", ())
            if isinstance(getattr(collection, "name", None), str)
        }

    def _collection_exists(self) -> bool:
        existing = self._list_collections()
        return self._collection_name in existing

    def _ensure_collection_exists(self) -> None:
        if self._initialized:
            return

        if not self._collection_exists():
            vector_distance = getattr(self._models.Distance, "COSINE", "Cosine")
            vector_config = self._models.VectorParams(
                size=self._VECTOR_DIMENSION,
                distance=vector_distance,
            )
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=vector_config,
            )
        self._initialized = True

    def _upsert_point(self, memory_id: str, vector: tuple[float, ...], archived: bool) -> None:
        point = {
            "id": memory_id,
            "vector": list(vector),
            "payload": self._vector_payload(memory_id, vector, archived=archived),
        }
        self._client.upsert(
            collection_name=self._collection_name,
            points=[point],
            wait=True,
        )

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        self._vectors[memory_id] = vector
        self._tombstones.discard(memory_id)
        self._upsert_point(memory_id, vector, archived=False)

    def delete(self, memory_id: str) -> None:
        vector = self._vectors.get(memory_id, vectorize(memory_id))
        self._tombstones.add(memory_id)
        self._upsert_point(memory_id, vector, archived=True)

    def _extract_point(self, point: object) -> tuple[str, tuple[float, ...], bool]:
        payload = _extract_payload(point)
        vector = _coerce_vector(getattr(point, "vector", payload.get("vector")))
        memory_id = str(getattr(point, "id", payload.get("memory_id", ""))).strip()
        archived = bool(payload.get("archived", False))
        return memory_id, vector, archived

    def _query_remote(self, query_vector: tuple[float, ...], limit: int) -> list[VectorMatch]:
        filter_clause = {"must_not": [{"key": "archived", "match": {"value": True}}]}
        matches: list[VectorMatch] = []

        try:
            response = self._client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                limit=limit,
                with_payload=True,
                with_vectors=True,
                query_filter=filter_clause,
            )
            raw_points = getattr(response, "points", ())
        except TypeError:
            response = self._client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                limit=limit,
                with_payload=True,
                with_vectors=True,
            )
            raw_points = getattr(response, "points", ())
        except Exception as exc:
            raise _QdrantRemoteQueryError("qdrant remote query failed") from exc

        for raw_point in raw_points:
            memory_id, vector, archived = self._extract_point(raw_point)
            if not memory_id:
                continue
            if memory_id in self._tombstones or archived:
                continue

            score = float(getattr(raw_point, "score", 0.0))
            if not score and vector:
                score = cosine_similarity(query_vector, vector)
            matches.append(VectorMatch(memory_id=memory_id, score=round(max(score, 0.0), 6)))
        return matches

    def _local_matches(self, query_vector: tuple[float, ...]) -> list[VectorMatch]:
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
        merged: dict[str, VectorMatch] = {}
        try:
            for match in self._query_remote(query_vector, limit=limit):
                merged[match.memory_id] = match
        except _QdrantRemoteQueryError as exc:
            warnings.warn(f"{exc}", RuntimeWarning, stacklevel=2)
        for match in self._local_matches(query_vector):
            if match.memory_id in self._tombstones or match.memory_id in merged:
                continue
            merged[match.memory_id] = match

        ordered = sorted(merged.values(), key=lambda result: (-result.score, result.memory_id))
        return tuple(ordered[:limit])


_BACKENDS: dict[tuple[str, str], _QdrantBackend] = {}


def _backend_for(connection_string: str) -> _QdrantBackend:
    endpoint, collection_name = _normalize_connection_and_collection(connection_string)
    key = (endpoint, collection_name)
    backend = _BACKENDS.get(key)
    if backend is None:
        backend = _QdrantBackend(connection_string)
        _BACKENDS[key] = backend
    return backend


class QdrantVectorStore:
    """Qdrant-backed vector index implementing shared vector operations."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _QdrantBackend | None = None,
    ) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        return self._backend.search(query, limit=limit)

    def delete(self, memory_id: str) -> None:
        self._backend.delete(memory_id)
