"""Weaviate-backed vector store with shared vector-contract behavior."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _MissingWeaviateDependencyError(RuntimeError):
    """Raised when Weaviate dependencies are unavailable."""


def _normalize_connection_and_collection(connection_string: str) -> tuple[str, str]:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)

    endpoint = (
        f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme
        else connection_string.split("?", 1)[0]
    )
    collection = query.get("collection", [parsed.path.strip("/")])[0].strip()
    return endpoint.rstrip("/"), collection or "cellin_vectors"


def _coerce_vector(value: object) -> tuple[float, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray)):
        return ()

    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return ()


def _coerce_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


class _WeaviateBackend:
    _VECTOR_DIMENSION = 12

    def __init__(self, connection_string: str) -> None:
        try:
            import weaviate  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingWeaviateDependencyError(
                "weaviate backend requires optional dependency `weaviate-client`"
            ) from exc

        endpoint, collection_name = _normalize_connection_and_collection(connection_string)
        self._collection_name = collection_name
        self._client = weaviate.Client(url=endpoint)
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._tombstones: set[str] = set()
        self._initialized = False
        self._ensure_collection_exists()

    def _ensure_collection_exists(self) -> None:
        if self._initialized:
            return

        collections = getattr(self._client, "collections", None)
        if collections is not None and hasattr(collections, "exists"):
            if not collections.exists(self._collection_name) and hasattr(collections, "create"):
                collections.create(
                    name=self._collection_name,
                    properties=[
                        {"name": "memory_id", "dataType": ["text"]},
                        {"name": "archived", "dataType": ["boolean"]},
                    ],
                )
            self._initialized = True
            return

        schema = getattr(self._client, "schema", None)
        if schema is None:
            self._initialized = True
            return

        schema_data = _coerce_mapping(schema.get() if callable(schema.get) else {})
        classes = schema_data.get("classes", ())
        if not isinstance(classes, (list, tuple)):
            classes = ()
        class_names = {str(item.get("class", "")) for item in classes if isinstance(item, Mapping)}
        if self._collection_name not in class_names and hasattr(schema, "create_class"):
            schema.create_class(
                {
                    "class": self._collection_name,
                    "vectorizer": "none",
                    "properties": [
                        {"name": "memory_id", "dataType": ["text"]},
                        {"name": "archived", "dataType": ["boolean"]},
                    ],
                }
            )
        self._initialized = True

    def _active_collection(self) -> Any:
        collections = getattr(self._client, "collections", None)
        if collections is not None and hasattr(collections, "get"):
            return collections.get(self._collection_name)
        return None

    def _upsert_remote(self, memory_id: str, vector: tuple[float, ...], archived: bool) -> None:
        collection = self._active_collection()
        if collection is not None and hasattr(collection, "data"):
            properties = {"memory_id": memory_id, "archived": archived}
            try:
                collection.data.insert(properties=properties, vector=list(vector))
            except TypeError:
                collection.data.insert(
                    {"memory_id": memory_id, "archived": archived}, vector=list(vector)
                )
            return

        data_object = getattr(self._client, "data_object", None)
        if data_object is not None and hasattr(data_object, "create"):
            data_object.create(
                class_name=self._collection_name,
                data_object={"memory_id": memory_id, "archived": archived},
                vector=list(vector),
            )

    def _query_objects(
        self, collection: Any, query_vector: tuple[float, ...], limit: int
    ) -> list[Any]:
        response = collection.query.near_vector(
            near_vector=list(query_vector),
            limit=limit,
            return_metadata=True,
            where={
                "path": ["archived"],
                "operator": "NotEqual",
                "valueBoolean": True,
            },
        )
        objects = getattr(response, "objects", ())
        if not isinstance(objects, (list, tuple)):
            return []
        return list(objects)

    def _local_matches(self, query_vector: tuple[float, ...]) -> list[VectorMatch]:
        return [
            VectorMatch(
                memory_id=memory_id,
                score=round(cosine_similarity(query_vector, vector), 6),
            )
            for memory_id, vector in self._vectors.items()
            if memory_id not in self._tombstones
        ]

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        self._vectors[memory_id] = vector
        self._tombstones.discard(memory_id)
        self._upsert_remote(memory_id, vector, archived=False)

    def delete(self, memory_id: str) -> None:
        self._tombstones.add(memory_id)
        vector = self._vectors.get(memory_id, vectorize(memory_id))
        self._upsert_remote(memory_id, vector, archived=True)

    def _query_collection(self, query_vector: tuple[float, ...], limit: int) -> list[VectorMatch]:
        collection = self._active_collection()
        if collection is None or not hasattr(collection, "query"):
            return []

        matches: list[VectorMatch] = []
        for obj in self._query_objects(collection, query_vector, limit):
            properties = _coerce_mapping(getattr(obj, "properties", {}))
            memory_id = str(properties.get("memory_id", "")).strip()
            archived = bool(properties.get("archived", False))
            if not memory_id or archived or memory_id in self._tombstones:
                continue

            metadata = _coerce_mapping(getattr(obj, "metadata", None))
            raw_score = metadata.get("certainty", 0.0)
            score = float(raw_score) if isinstance(raw_score, int | float) else 0.0
            if score == 0.0:
                score = cosine_similarity(query_vector, self._vectors.get(memory_id, ()))
            matches.append(VectorMatch(memory_id=memory_id, score=round(max(score, 0.0), 6)))
        return matches

    def _query_fallback(self, query_vector: tuple[float, ...], limit: int) -> list[VectorMatch]:
        if not hasattr(self._client, "query"):
            return []

        results: list[VectorMatch] = []
        _ = query_vector, limit
        return results

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        matches = self._query_collection(query_vector, limit=limit)
        fallback = self._query_fallback(query_vector, limit=limit)
        if fallback:
            for match in fallback:
                if match.memory_id not in {existing.memory_id for existing in matches}:
                    matches.append(match)

        existing = {result.memory_id for result in matches}
        for local in self._local_matches(query_vector):
            if local.memory_id in existing:
                continue
            matches.append(local)
            existing.add(local.memory_id)

        ordered = sorted(matches, key=lambda item: (-item.score, item.memory_id))
        return tuple(ordered[:limit])


_BACKENDS: dict[tuple[str, str], _WeaviateBackend] = {}


def _backend_for(connection_string: str) -> _WeaviateBackend:
    endpoint, collection_name = _normalize_connection_and_collection(connection_string)
    key = (endpoint, collection_name)
    backend = _BACKENDS.get(key)
    if backend is None:
        backend = _WeaviateBackend(connection_string)
        _BACKENDS[key] = backend
    return backend


class WeaviateVectorStore:
    """Weaviate-backed vector index implementing shared vector operations."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _WeaviateBackend | None = None,
    ) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        return self._backend.search(query, limit=limit)

    def delete(self, memory_id: str) -> None:
        self._backend.delete(memory_id)
