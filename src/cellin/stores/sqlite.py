"""SQLite-backed memory and graph persistence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from cellin.core import MemoryAtom, MemoryEdge, MemoryStore
from cellin.stores._graph_serialization import (
    dump_edge as _dump_edge,
)
from cellin.stores._graph_serialization import (
    dump_memory as _dump_memory,
)
from cellin.stores._graph_serialization import (
    edge_is_archived as _edge_archived,
)
from cellin.stores._graph_serialization import (
    load_edge as _load_edge,
)
from cellin.stores._graph_serialization import (
    load_memory as _load_memory,
)


class _SQLiteBackend:
    """Shared SQLite boundary for memory and graph persistence."""

    _MEMORY_DB = "file::memory:?cache=shared"

    def __init__(self, database_path: str) -> None:
        self._is_memory_db = database_path == ":memory:"
        self.database_path = self._MEMORY_DB if self._is_memory_db else database_path
        self._memory_connection: sqlite3.Connection | None = None
        self._ensure_parent_directory()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if not self._is_memory_db:
            return sqlite3.connect(self.database_path)
        if self._memory_connection is None:
            self._memory_connection = sqlite3.connect(self.database_path, uri=True)
        return self._memory_connection

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

    def _ensure_parent_directory(self) -> None:
        if self._is_memory_db:
            return
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

    def _initialize(self) -> None:
        with self._connected(writable=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def put_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        if not memories:
            return
        rows = [(memory.memory_id, _dump_memory(memory)) for memory in memories]
        with self._connected(writable=True) as connection:
            connection.executemany(
                """
                INSERT INTO memories(memory_id, payload)
                VALUES (?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET payload = excluded.payload
                """,
                rows,
            )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        with self._connected() as connection:
            row = connection.execute(
                "SELECT payload FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return _load_memory(row[0])

    def list_memories(self) -> tuple[MemoryAtom, ...]:
        with self._connected() as connection:
            rows = connection.execute("SELECT payload FROM memories ORDER BY memory_id").fetchall()
        return tuple(_load_memory(row[0]) for row in rows)

    def list_memories_by(
        self,
        *,
        archived: bool | None = None,
        topic: str | None = None,
    ) -> list[MemoryAtom]:
        conditions: list[str] = []
        params: list[object] = []
        if archived is not None:
            conditions.append("json_extract(payload, '$.decay.archived') = ?")
            params.append(1 if archived else 0)
        if topic is not None:
            conditions.append("json_extract(payload, '$.metadata.topic') = ?")
            params.append(topic)
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT payload FROM memories {where_clause} ORDER BY memory_id"
        with self._connected() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_load_memory(row[0]) for row in rows]

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        if not edges:
            return
        rows = [(edge.edge_id, edge.source_id, edge.target_id, _dump_edge(edge)) for edge in edges]
        with self._connected(writable=True) as connection:
            connection.executemany(
                """
                INSERT INTO edges(edge_id, source_id, target_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET payload = excluded.payload
                """,
                rows,
            )

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        with self._connected() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM edges
                WHERE source_id = ? OR target_id = ?
                ORDER BY edge_id
                """,
                (memory_id, memory_id),
            ).fetchall()
        return tuple(edge for row in rows if not _edge_archived(edge := _load_edge(row[0])))

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        with self._connected() as connection:
            rows = connection.execute("SELECT payload FROM edges ORDER BY edge_id").fetchall()
        return tuple(edge for row in rows if not _edge_archived(edge := _load_edge(row[0])))


_BACKENDS: dict[str, _SQLiteBackend] = {}


def _backend_for(database_path: str) -> _SQLiteBackend:
    resolved_path = (
        database_path if database_path == ":memory:" else str(Path(database_path).resolve())
    )
    backend = _BACKENDS.get(resolved_path)
    if backend is None:
        backend = _SQLiteBackend(resolved_path)
        _BACKENDS[resolved_path] = backend
    return backend


class _SQLiteBase:
    def __init__(self, database_path: str, *, backend: _SQLiteBackend | None = None) -> None:
        self._backend = backend or _backend_for(database_path)
        self._database_path = self._backend.database_path


class SQLiteMemoryStore(_SQLiteBase):
    """Persists memory atoms in SQLite as JSON payloads."""

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()

    def list_by(
        self,
        *,
        archived: bool | None = None,
        topic: str | None = None,
    ) -> Sequence[MemoryAtom]:
        """Return memories filtered by archived state and/or topic using SQL WHERE clauses."""
        return self._backend.list_memories_by(archived=archived, topic=topic)


class SQLiteGraphStore(_SQLiteBase):
    """Persists graph edges and reads graph-backed memory state from SQLite."""

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
            isinstance(memory_store, SQLiteMemoryStore) and memory_store._backend is self._backend
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
