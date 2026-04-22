"""SQLite-backed vector index using the shared vector store contract."""

from __future__ import annotations

import heapq
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _VectorBackend:
    """Shared low-level helper for vector persistence in SQLite."""

    def __init__(self, database_path: str) -> None:
        self._is_memory_db = database_path == ":memory:"
        if self._is_memory_db:
            self.database_path = "file::memory:?cache=shared"
        else:
            resolved_path = Path(database_path)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            self.database_path = str(resolved_path)
        self._memory_connection: sqlite3.Connection | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._is_memory_db:
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(self.database_path, uri=True)
            return self._memory_connection
        return sqlite3.connect(self.database_path)

    @contextmanager
    def _connected(self, *, writable: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        if self._is_memory_db:
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                if writable:
                    connection.commit()
            return

        if writable:
            with closing(connection):
                with connection:
                    yield connection
        else:
            with closing(connection):
                yield connection

    def _initialize(self) -> None:
        with self._connected(writable=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_entries (
                    memory_id TEXT PRIMARY KEY,
                    vector TEXT NOT NULL
                )
                """
            )

    def _iter_vectors(self) -> Iterator[tuple[str, tuple[float, ...]]]:
        with self._connected() as connection:
            for row in connection.execute("SELECT memory_id, vector FROM vector_entries"):
                yield row[0], tuple(float(value) for value in json.loads(row[1]))

    def list_vectors(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        return tuple(self._iter_vectors())

    def upsert(self, memory_id: str, vector: tuple[float, ...]) -> None:
        with self._connected(writable=True) as connection:
            connection.execute(
                """
                INSERT INTO vector_entries(memory_id, vector)
                VALUES (?, ?)
                ON CONFLICT(memory_id) DO UPDATE
                SET vector = excluded.vector
                """,
                (memory_id, json.dumps(vector)),
            )

    def delete(self, memory_id: str) -> None:
        with self._connected(writable=True) as connection:
            connection.execute(
                "DELETE FROM vector_entries WHERE memory_id = ?",
                (memory_id,),
            )


class SQLiteVecStore:
    """SQLite-backed vector storage and top-k cosine search."""

    def __init__(self, database_path: str) -> None:
        self._backend = _VectorBackend(database_path)

    def upsert(self, memory_id: str, text: str) -> None:
        self._backend.upsert(memory_id, vectorize(text))

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        candidate_matches = (
            VectorMatch(
                memory_id=memory_id,
                score=round(cosine_similarity(query_vector, vector), 6),
            )
            for memory_id, vector in self._backend._iter_vectors()
        )
        results = heapq.nlargest(limit, candidate_matches, key=lambda match: match.score)

        ordered = sorted(results, key=lambda result: (-result.score, result.memory_id))
        return tuple(ordered)

    def delete(self, memory_id: str) -> None:
        """Remove an indexed vector for a memory id if present."""
        self._backend.delete(memory_id)
