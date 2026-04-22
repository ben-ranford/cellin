"""Shared SQL-backed memory and graph stores for first-party relational backends."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import unquote, urlparse

from cellin.core import MemoryAtom, MemoryEdge, MemoryStore
from cellin.stores._graph_serialization import (
    dump_edge,
    dump_memory,
    edge_is_archived,
    load_edge,
    load_memory,
)


class _MissingDuckDBDependencyError(RuntimeError):
    """Raised when DuckDB is unavailable from runtime dependencies."""


class _MissingPostgreSQLDependencyError(RuntimeError):
    """Raised when psycopg is unavailable from runtime dependencies."""


class _MissingMySQLDependencyError(RuntimeError):
    """Raised when a MySQL driver is unavailable from runtime dependencies."""


class _QueryResult(Protocol):
    def fetchall(self) -> list[tuple[Any, ...]]: ...


class _ExecutableConnection(Protocol):
    def execute(self, query: str, parameters: Sequence[object] | None = None) -> _QueryResult: ...

    def executemany(self, query: str, rows: Sequence[tuple[object, ...]]) -> None: ...

    def __enter__(self) -> _ExecutableConnection: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


@dataclass(frozen=True)
class _BackendSpec:
    parameter_style: str
    upsert_memory_sql: str
    upsert_edge_sql: str


class _RelationalBackend:
    _MEMORY_GET_SQL = "SELECT payload FROM memories WHERE memory_id = ?"
    _MEMORY_LIST_SQL = "SELECT payload FROM memories ORDER BY memory_id"
    _NEIGHBORS_SQL = """
    SELECT payload
    FROM edges
    WHERE source_id = ? OR target_id = ?
    ORDER BY edge_id
    """
    _EDGES_LIST_SQL = "SELECT payload FROM edges ORDER BY edge_id"

    def __init__(
        self,
        connection_key: str,
        connect: Callable[[], _ExecutableConnection],
        *,
        spec: _BackendSpec,
    ) -> None:
        self._connection_key = connection_key
        self._connect = connect
        self._spec = spec
        self._initialized = False
        self._ensure_schema()

    @staticmethod
    def _consume_result(result: _QueryResult) -> None:
        result.fetchall()

    @staticmethod
    def _parametrize(query: str, parameter_style: str) -> str:
        return query.replace("?", parameter_style)

    def _execute(
        self,
        connection: _ExecutableConnection,
        query: str,
        parameters: Sequence[object] = (),
    ) -> _QueryResult | None:
        return connection.execute(query, tuple(parameters) if parameters else ())

    def _fetch_one(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> tuple[Any, ...] | None:
        with self._connect() as connection:
            result = self._execute(
                connection,
                self._parametrize(query, self._spec.parameter_style),
                parameters,
            )
            if result is None:
                return None
            rows = tuple(result.fetchall())
        return rows[0] if rows else None

    def _fetch_all(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> tuple[tuple[Any, ...], ...]:
        with self._connect() as connection:
            result = self._execute(
                connection,
                self._parametrize(query, self._spec.parameter_style),
                parameters,
            )
            if result is None:
                return ()
            return tuple(result.fetchall())

    def _execute_many(self, query: str, rows: Sequence[tuple[object, ...]]) -> None:
        if not rows:
            return

        with self._connect() as connection:
            connection.executemany(query, rows)

    def _ensure_schema(self) -> None:
        """Initialize schema exactly once per backend key."""
        if self._initialized:
            return

        schema_statements = (
            """
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """,
        )

        with self._connect() as connection:
            for statement in schema_statements:
                result = self._execute(connection, statement)
                if result is not None:
                    self._consume_result(result)

        self._initialized = True

    def put_memories(self, memories: Sequence[MemoryAtom]) -> None:
        if not memories:
            return

        rows = tuple((memory.memory_id, dump_memory(memory)) for memory in memories)
        self._execute_many(
            self._parametrize(self._spec.upsert_memory_sql, self._spec.parameter_style),
            rows,
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        row = self._fetch_one(self._MEMORY_GET_SQL, (memory_id,))
        if row is None:
            return None
        return load_memory(row[0])

    def list_memories(self) -> tuple[MemoryAtom, ...]:
        rows = self._fetch_all(self._MEMORY_LIST_SQL)
        return tuple(load_memory(row[0]) for row in rows)

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        if not edges:
            return

        rows = tuple(
            (edge.edge_id, edge.source_id, edge.target_id, dump_edge(edge)) for edge in edges
        )
        self._execute_many(
            self._parametrize(self._spec.upsert_edge_sql, self._spec.parameter_style),
            rows,
        )

    def get_neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        rows = self._fetch_all(self._NEIGHBORS_SQL, (memory_id, memory_id))
        return tuple(
            edge
            for row in rows
            if not edge_is_archived(
                edge := load_edge(row[0]),
            )
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        rows = self._fetch_all(self._EDGES_LIST_SQL)
        return tuple(
            edge
            for row in rows
            if not edge_is_archived(
                edge := load_edge(row[0]),
            )
        )


_BACKENDS: dict[tuple[str, str], _RelationalBackend] = {}


def _backend_for(
    label: str,
    connection_key: str,
    connect: Callable[[], _ExecutableConnection],
    *,
    parameter_style: str,
    upsert_memory_sql: str,
    upsert_edge_sql: str,
) -> _RelationalBackend:
    backend_key = (label, connection_key)
    backend = _BACKENDS.get(backend_key)
    if backend is None:
        backend = _RelationalBackend(
            connection_key,
            connect,
            spec=_BackendSpec(
                parameter_style=parameter_style,
                upsert_memory_sql=upsert_memory_sql,
                upsert_edge_sql=upsert_edge_sql,
            ),
        )
        _BACKENDS[backend_key] = backend
    return backend


def _build_duckdb_connection(database_path: str) -> Callable[[], _ExecutableConnection]:
    def connect() -> _ExecutableConnection:
        try:
            import duckdb  # type: ignore[import-not-found]
        except ImportError as exc:
            raise _MissingDuckDBDependencyError(
                "duckdb backend requires optional dependency `duckdb`"
            ) from exc

        return cast(_ExecutableConnection, duckdb.connect(database_path))

    return connect


def _build_postgresql_connection(connection_string: str) -> Callable[[], _ExecutableConnection]:
    def connect() -> _ExecutableConnection:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise _MissingPostgreSQLDependencyError(
                "postgresql backend requires optional dependency `psycopg`"
            ) from exc

        return cast(_ExecutableConnection, psycopg.connect(connection_string))

    return connect


def _resolve_file_path(database_path: str) -> str:
    if database_path == ":memory:":
        return database_path
    return str(Path(database_path).resolve())


@dataclass(frozen=True)
class _MySQLConnectionParams:
    user: str | None
    password: str | None
    host: str | None
    port: int | None
    database: str | None


def _parse_mysql_connection_string(connection_string: str) -> _MySQLConnectionParams:
    parsed = urlparse(connection_string)
    if parsed.scheme not in {
        "mysql",
        "mysql+mysqlconnector",
        "mysql+mysql-connector-python",
    }:
        raise ValueError("mysql backend requires a mysql:// connection string")

    return _MySQLConnectionParams(
        user=unquote(parsed.username) if parsed.username is not None else None,
        password=unquote(parsed.password) if parsed.password is not None else None,
        host=parsed.hostname,
        port=parsed.port,
        database=(parsed.path[1:] if parsed.path else None) or None,
    )


class _MySQLCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self._cursor.fetchall()
        self._cursor.close()
        return list(rows)


class _MySQLConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __enter__(self) -> _MySQLConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._connection.close()

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> _QueryResult:
        cursor = self._connection.cursor()
        cursor.execute(query, tuple(parameters) if parameters else ())
        return _MySQLCursor(cursor)

    def executemany(self, query: str, rows: Sequence[tuple[object, ...]]) -> None:
        cursor = self._connection.cursor()
        cursor.executemany(query, list(rows))
        cursor.close()


def _build_mysql_connection(connection_string: str) -> Callable[[], _ExecutableConnection]:
    def connect() -> _ExecutableConnection:
        try:
            from mysql import connector  # type: ignore[import-not-found]
        except ImportError as exc:
            raise _MissingMySQLDependencyError(
                "mysql backend requires optional dependency `mysql-connector-python`"
            ) from exc

        parsed = _parse_mysql_connection_string(connection_string)

        connection_kwargs: dict[str, object] = {"autocommit": True}
        if parsed.user is not None:
            connection_kwargs["user"] = parsed.user
        if parsed.password is not None:
            connection_kwargs["password"] = parsed.password
        if parsed.host is not None:
            connection_kwargs["host"] = parsed.host
        if parsed.port is not None:
            connection_kwargs["port"] = parsed.port
        if parsed.database is not None:
            connection_kwargs["database"] = parsed.database

        connection = connector.connect(**connection_kwargs)
        return _MySQLConnection(connection)

    return connect


_DUCKDB_MEMORY_UPSERT_SQL = """
INSERT INTO memories(memory_id, payload)
VALUES (?, ?)
ON CONFLICT(memory_id) DO UPDATE SET payload = excluded.payload
"""

_DUCKDB_EDGE_UPSERT_SQL = """
INSERT INTO edges(edge_id, source_id, target_id, payload)
VALUES (?, ?, ?, ?)
ON CONFLICT(edge_id) DO UPDATE SET payload = excluded.payload
"""

_POSTGRES_MEMORY_UPSERT_SQL = """
INSERT INTO memories(memory_id, payload)
VALUES (%s, %s)
ON CONFLICT(memory_id) DO UPDATE SET payload = EXCLUDED.payload
"""

_POSTGRES_EDGE_UPSERT_SQL = """
INSERT INTO edges(edge_id, source_id, target_id, payload)
VALUES (%s, %s, %s, %s)
ON CONFLICT(edge_id) DO UPDATE SET payload = EXCLUDED.payload
"""

_MYSQL_MEMORY_UPSERT_SQL = """
INSERT INTO memories(memory_id, payload)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE payload = VALUES(payload)
"""

_MYSQL_EDGE_UPSERT_SQL = """
INSERT INTO edges(edge_id, source_id, target_id, payload)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE payload = VALUES(payload)
"""


class DuckDBMemoryStore:
    """Relational memory store backed by DuckDB."""

    def __init__(self, database_path: str) -> None:
        self._database_path = _resolve_file_path(database_path)
        self._backend = _backend_for(
            "duckdb",
            self._database_path,
            _build_duckdb_connection(self._database_path),
            parameter_style="?",
            upsert_memory_sql=_DUCKDB_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_DUCKDB_EDGE_UPSERT_SQL,
        )

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class DuckDBGraphStore:
    """Relational graph store backed by DuckDB."""

    def __init__(self, database_path: str) -> None:
        self._database_path = _resolve_file_path(database_path)
        self._backend = _backend_for(
            "duckdb",
            self._database_path,
            _build_duckdb_connection(self._database_path),
            parameter_style="?",
            upsert_memory_sql=_DUCKDB_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_DUCKDB_EDGE_UPSERT_SQL,
        )

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edges((edge,))

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return (
            isinstance(memory_store, DuckDBMemoryStore) and memory_store._backend is self._backend
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.get_neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()


class PostgreSQLMemoryStore:
    """Relational memory store backed by PostgreSQL."""

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._backend = _backend_for(
            "postgresql",
            connection_string,
            _build_postgresql_connection(connection_string),
            parameter_style="%s",
            upsert_memory_sql=_POSTGRES_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_POSTGRES_EDGE_UPSERT_SQL,
        )

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class PostgreSQLGraphStore:
    """Relational graph store backed by PostgreSQL."""

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._backend = _backend_for(
            "postgresql",
            connection_string,
            _build_postgresql_connection(connection_string),
            parameter_style="%s",
            upsert_memory_sql=_POSTGRES_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_POSTGRES_EDGE_UPSERT_SQL,
        )

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edges((edge,))

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return (
            isinstance(memory_store, PostgreSQLMemoryStore)
            and memory_store._backend is self._backend
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.get_neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()


class MySQLMemoryStore:
    """Relational memory store backed by MySQL."""

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._backend = _backend_for(
            "mysql",
            connection_string,
            _build_mysql_connection(connection_string),
            parameter_style="%s",
            upsert_memory_sql=_MYSQL_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_MYSQL_EDGE_UPSERT_SQL,
        )

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class MySQLGraphStore:
    """Relational graph store backed by MySQL."""

    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._backend = _backend_for(
            "mysql",
            connection_string,
            _build_mysql_connection(connection_string),
            parameter_style="%s",
            upsert_memory_sql=_MYSQL_MEMORY_UPSERT_SQL,
            upsert_edge_sql=_MYSQL_EDGE_UPSERT_SQL,
        )

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: Sequence[MemoryAtom]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edges((edge,))

    def upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return isinstance(memory_store, MySQLMemoryStore) and memory_store._backend is self._backend

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.get_neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()


__all__ = [
    "DuckDBMemoryStore",
    "DuckDBGraphStore",
    "PostgreSQLMemoryStore",
    "PostgreSQLGraphStore",
    "MySQLMemoryStore",
    "MySQLGraphStore",
]
