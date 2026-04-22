"""Shared base class for remote vector backends."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity


def normalize_connection_and_collection(connection_string: str) -> tuple[str, str]:
    """Parse a connection string into (endpoint, collection_name).

    Handles the common URL-query pattern shared by Qdrant, Weaviate, and Milvus:
    - ``scheme://host/path?collection=name`` → (``scheme://host``, ``name``)
    - ``?collection=name`` → (``""``, ``name``)
    - ``scheme://host/path`` → (``scheme://host``, ``path``)
    """
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query)

    collection = query.get("collection", [parsed.path.strip("/")])[0].strip()

    if parsed.scheme:
        endpoint = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    else:
        endpoint = connection_string.split("?", 1)[0]

    return endpoint.rstrip("/"), collection or "cellin_vectors"


class _RemoteVectorBackendBase:
    """Shared state and helpers for remote vector store backends.

    Subclasses must implement ``_query_remote`` and ``_ensure_collection_exists``.
    The ``_local_matches`` method and ``_vectors``/``_tombstones`` state are
    provided here to avoid copy-pasting across backends.
    """

    _vectors: dict[str, tuple[float, ...]]
    _tombstones: set[str]

    def _local_matches(self, query_vector: tuple[float, ...]) -> list[VectorMatch]:
        """Return ``VectorMatch`` objects for every non-tombstoned locally cached vector."""
        return [
            VectorMatch(
                memory_id=memory_id,
                score=round(cosine_similarity(query_vector, vector), 6),
            )
            for memory_id, vector in self._vectors.items()
            if memory_id not in self._tombstones
        ]
