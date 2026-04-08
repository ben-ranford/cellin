"""PostgreSQL/pgvector-backed vector index abstraction."""

from __future__ import annotations

import re
from typing import Any

from cellin.core import VectorMatch
from cellin.stores.vector_utils import vectorize


class _MissingPgVectorDependencyError(RuntimeError):
    """Raised when pgvector is unavailable from runtime dependencies."""


_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _require_valid_table_name(table_name: str) -> str:
    if _TABLE_NAME_RE.fullmatch(table_name) is None:
        raise ValueError("pgvector table name must be a safe SQL identifier")
    return _quote_identifier(table_name)


class PGVectorStore:
    """Vector index backed by PostgreSQL + pgvector.

    The implementation is intentionally lightweight and validates dependencies on
    first use so optional installs remain possible.
    """

    def __init__(self, connection_string: str, *, table_name: str = "cellin_vectors") -> None:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise _MissingPgVectorDependencyError(
                "pgvector backend requires optional dependency `psycopg`"
            ) from exc

        self._psycopg = psycopg
        self._connection_string = connection_string
        self._table_name = _require_valid_table_name(table_name)
        self._initialized = False
        self._ensure_schema()

    def _connect(self) -> Any:
        return self._psycopg.connect(self._connection_string)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return

        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    memory_id TEXT PRIMARY KEY,
                    vector vector(12)
                )
                """
            )
        self._initialized = True

    def upsert(self, memory_id: str, text: str) -> None:
        vector = vectorize(text)
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._table_name}(memory_id, vector)
                VALUES (%s, %s)
                ON CONFLICT(memory_id) DO UPDATE SET vector = EXCLUDED.vector
                """,
                (memory_id, vector),
            )

    def search(self, query: str, *, limit: int = 5) -> tuple[VectorMatch, ...]:
        if limit <= 0:
            return ()

        query_vector = vectorize(query)
        matches: list[VectorMatch] = []
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_id, vector <=> %s AS distance
                FROM {self._table_name}
                ORDER BY distance
                LIMIT %s
                """,
                (query_vector, limit),
            ).fetchall()

        for row in rows:
            memory_id, distance = row
            score = 1.0 - float(distance)
            matches.append(VectorMatch(memory_id=memory_id, score=round(max(score, 0.0), 6)))

        return tuple(matches)
