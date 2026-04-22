"""Redis-backed vector store with shared vector-contract behavior."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _MissingRedisDependencyError(RuntimeError):
    """Raised when Redis dependencies are unavailable."""


def _escape_scan_match(value: str) -> str:
    escaped = value
    for pattern_char in ("\\", "*", "?", "[", "]"):
        escaped = escaped.replace(pattern_char, "\\" + pattern_char)
    return escaped


def _parse_namespace(connection_string: str) -> tuple[str, str]:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)
    db = parsed.path.strip("/") or "0"
    namespace = f"cellin:{db}"
    collection = query.get("collection", [""])[0].strip()
    collection_name = collection or "cellin_vectors"
    return namespace, collection_name


class _RedisVectorBackend:
    def __init__(self, connection_string: str) -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingRedisDependencyError(
                "redis vector backend requires optional dependency `redis`"
            ) from exc

        self._namespace, self._collection = _parse_namespace(connection_string)
        self._backend_key = f"{self._namespace}:collection:{self._collection}"
        self._client = redis.Redis.from_url(connection_string, decode_responses=True)
        self._tombstones: set[str] = set()
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._initialized = False
        self._initialize_collection()

    def _initialize_collection(self) -> None:
        if self._initialized:
            return
        self._client.set(self._backend_key, "initialized", nx=True)
        self._initialized = True

    def _key(self, memory_id: str) -> str:
        return f"{self._namespace}:vector:{self._collection}:{memory_id}"

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        self._vectors[memory_id] = vector
        self._tombstones.discard(memory_id)
        payload = {"memory_id": memory_id, "archived": False, "vector": list(vector)}
        self._client.set(self._key(memory_id), json.dumps(payload))

    def delete(self, memory_id: str) -> None:
        self._tombstones.add(memory_id)
        vector = self._vectors.get(memory_id, vectorize(memory_id))
        payload = {"memory_id": memory_id, "archived": True, "vector": list(vector)}
        self._client.set(self._key(memory_id), json.dumps(payload))

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        matches: list[VectorMatch] = []
        pattern = f"{self._namespace}:vector:{_escape_scan_match(self._collection)}:*"
        for key in self._client.scan_iter(match=pattern):
            payload = self._client.get(key)
            if payload is None:
                continue

            try:
                document = json.loads(payload)
            except json.JSONDecodeError:
                continue

            memory_id = str(document.get("memory_id", ""))
            if not memory_id or memory_id in self._tombstones or document.get("archived"):
                continue
            vector = tuple(float(value) for value in document.get("vector", ()))
            if not vector:
                continue
            score = round(cosine_similarity(query_vector, vector), 6)
            matches.append(VectorMatch(memory_id=memory_id, score=score))

        ordered = sorted(matches, key=lambda item: (-item.score, item.memory_id))
        return tuple(ordered[:limit])


_BACKENDS: dict[tuple[str, str, str], _RedisVectorBackend] = {}


def _backend_for(connection_string: str) -> _RedisVectorBackend:
    namespace, collection = _parse_namespace(connection_string)
    key = (connection_string, namespace, collection)
    backend = _BACKENDS.get(key)
    if backend is None:
        backend = _RedisVectorBackend(connection_string)
        _BACKENDS[key] = backend
    return backend


class RedisVectorStore:
    """Redis-backed vector index implementing shared vector operations."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _RedisVectorBackend | None = None,
    ) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        return self._backend.search(query, limit=limit)

    def delete(self, memory_id: str) -> None:
        self._backend.delete(memory_id)
