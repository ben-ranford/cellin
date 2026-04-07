"""Pinecone-backed vector store with shared vector-contract behavior."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _MissingPineconeDependencyError(RuntimeError):
    """Raised when Pinecone dependencies are unavailable."""


def _normalize_connection_and_index(connection_string: str) -> tuple[str, str | None, str, str]:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)

    if parsed.scheme and parsed.netloc:
        endpoint = f"{parsed.scheme}://{parsed.netloc}"
    else:
        endpoint = connection_string.split("/", 1)[0].split("?", 1)[0]
    api_key = query.get("api_key", [None])[0]
    if api_key is None and parsed.username:
        api_key = parsed.username

    path_index = parsed.path.strip("/") if "://" in connection_string else ""
    index_from_query = query.get("index", [])
    index_name = path_index or (index_from_query[0] if index_from_query else "cellin_vectors")
    namespace = query.get("namespace", ["default"])[0].strip() or "default"

    return endpoint.rstrip("/"), api_key, index_name, namespace


def _index_names(client: object) -> set[str]:
    list_indexes = getattr(client, "list_indexes", None)
    if not callable(list_indexes):
        return set()

    raw_indexes = list_indexes()
    if isinstance(raw_indexes, dict):
        raw_indexes = raw_indexes.get("indexes", [])
    if isinstance(raw_indexes, set):
        return set(raw_indexes)

    return {str(item) for item in raw_indexes}


class _PineconeBackend:
    _VECTOR_DIMENSION = 12

    def __init__(self, connection_string: str) -> None:
        try:
            import pinecone  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingPineconeDependencyError(
                "pinecone backend requires optional dependency `pinecone-client`"
            ) from exc

        _, api_key, index_name, namespace = _normalize_connection_and_index(connection_string)
        self._client = pinecone
        self._index_name = index_name
        self._api_key = api_key
        self._namespace = namespace
        self._environment: str | None = None
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._tombstones: set[str] = set()
        self._index = self._connect()
        self._initialized = False
        self._ensure_index_exists()

    def _connect(self) -> Any:
        if hasattr(self._client, "Pinecone"):
            connector = self._client.Pinecone(
                api_key=self._api_key or "",
                environment=self._environment or "us-east-1",
            )
            return connector.Index(self._index_name)
        self._client.init(
            api_key=self._api_key or "",
            environment=self._environment or "us-east-1",
        )
        return self._client.Index(self._index_name)

    def _ensure_index_exists(self) -> None:
        if self._initialized:
            return

        indexes = _index_names(self._client)
        if self._index_name not in indexes:
            create_index = getattr(self._client, "create_index", None)
            if callable(create_index):
                create_index(
                    name=self._index_name,
                    dimension=self._VECTOR_DIMENSION,
                    metric="cosine",
                )
        self._initialized = True

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        self._vectors[memory_id] = vector
        self._tombstones.discard(memory_id)
        self._index.upsert(
            vectors=[
                {
                    "id": memory_id,
                    "values": list(vector),
                    "metadata": {"memory_id": memory_id, "archived": False},
                }
            ],
            namespace=self._namespace,
        )

    def delete(self, memory_id: str) -> None:
        vector = self._vectors.get(memory_id, vectorize(memory_id))
        self._tombstones.add(memory_id)
        self._index.upsert(
            vectors=[
                {
                    "id": memory_id,
                    "values": list(vector),
                    "metadata": {"memory_id": memory_id, "archived": True},
                }
            ],
            namespace=self._namespace,
        )

    def _query_remote(self, query_vector: tuple[float, ...], limit: int) -> list[VectorMatch]:
        try:
            response = self._index.query(
                vector=list(query_vector),
                top_k=limit,
                include_values=False,
                include_metadata=True,
                namespace=self._namespace,
                filter={"archived": {"$ne": True}},
            )
        except TypeError:
            response = self._index.query(
                vector=list(query_vector),
                top_k=limit,
                namespace=self._namespace,
            )

        matches: list[VectorMatch] = []
        for match in getattr(response, "matches", ()) or ():
            metadata = getattr(match, "metadata", {}) or {}
            memory_id = str(metadata.get("memory_id", getattr(match, "id", "")))
            if not memory_id or memory_id in self._tombstones or metadata.get("archived", False):
                continue
            score = float(getattr(match, "score", 0.0))
            matches.append(VectorMatch(memory_id=memory_id, score=round(max(score, 0.0), 6)))
        return matches

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        matches = self._query_remote(query_vector, limit=limit)
        if len(matches) < limit:
            existing = {match.memory_id for match in matches}
            for memory_id, vector in self._vectors.items():
                if memory_id in self._tombstones or memory_id in existing:
                    continue
                score = round(cosine_similarity(query_vector, vector), 6)
                matches.append(VectorMatch(memory_id=memory_id, score=score))
                existing.add(memory_id)
        ordered = sorted(matches, key=lambda item: (-item.score, item.memory_id))
        return tuple(ordered[:limit])


_BACKENDS: dict[tuple[str, str, str], _PineconeBackend] = {}


def _backend_for(connection_string: str) -> _PineconeBackend:
    _, api_key, index_name, namespace = _normalize_connection_and_index(connection_string)
    key = (api_key or "", index_name, namespace)
    backend = _BACKENDS.get(key)
    if backend is None:
        backend = _PineconeBackend(connection_string)
        _BACKENDS[key] = backend
    return backend


class PineconeVectorStore:
    """Pinecone-backed vector index implementing shared vector operations."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _PineconeBackend | None = None,
    ) -> None:
        self._backend = _backend or _backend_for(connection_string)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, text)

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        return self._backend.search(query, limit=limit)

    def delete(self, memory_id: str) -> None:
        self._backend.delete(memory_id)
