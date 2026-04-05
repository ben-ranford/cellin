"""SQLite-backed vector index using the shared vector store contract."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cellin.core import VectorMatch
from cellin.stores.vector_utils import cosine_similarity, vectorize


class _VectorBackend:
    """Shared low-level helper for vector persistence in SQLite."""

    def __init__(self, database_path: str) -> None:
        resolved_path = Path(database_path)
        if resolved_path != Path(":memory:"):
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = str(resolved_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_entries (
                    memory_id TEXT PRIMARY KEY,
                    vector TEXT NOT NULL
                )
                """
            )

    def upsert(self, memory_id: str, vector: tuple[float, ...]) -> None:
        connection = self._connect()
        with connection:
            connection.execute(
                """
                INSERT INTO vector_entries(memory_id, vector)
                VALUES (?, ?)
                ON CONFLICT(memory_id) DO UPDATE
                SET vector = excluded.vector
                """,
                (memory_id, json.dumps(vector)),
            )
        connection.close()

    def list_vectors(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT memory_id, vector FROM vector_entries").fetchall()

        return tuple((row[0], tuple(float(value) for value in json.loads(row[1]))) for row in rows)


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
        results: list[VectorMatch] = []
        for memory_id, vector in self._backend.list_vectors():
            score = round(cosine_similarity(query_vector, vector), 6)
            results.append(VectorMatch(memory_id=memory_id, score=score))

        ordered = sorted(results, key=lambda result: (-result.score, result.memory_id))
        return tuple(ordered[:limit])
