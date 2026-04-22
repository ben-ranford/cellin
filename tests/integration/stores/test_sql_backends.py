"""Integration coverage for first-party SQL memory and graph backends."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from types import ModuleType

import pytest

from cellin.core import (
    DecayState,
    EdgeKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.stores import (
    DuckDBGraphStore,
    DuckDBMemoryStore,
    MySQLGraphStore,
    MySQLMemoryStore,
    PostgreSQLGraphStore,
    PostgreSQLMemoryStore,
    sql_backends,
)


def _memory(memory_id: str, text: str) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        observed_at=datetime(2026, 4, 5, tzinfo=UTC),
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


def _edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    archived: bool,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        metadata={"archived": archived},
    )


class _FakeSQLResult:
    def __init__(self, rows: Sequence[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeSQLEngine:
    def __init__(self) -> None:
        self.memories: dict[str, str] = {}
        self.edges: dict[str, tuple[str, str, str]] = {}
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: Sequence[object] = ()) -> list[tuple[object, ...]]:
        normalized_query = " ".join(query.lower().split())
        params = tuple(parameters)
        self.queries.append((query, params))

        if self._is_schema_query(normalized_query):
            return []

        memory_rows = self._handle_memory_query(normalized_query, params)
        if memory_rows is not None:
            return memory_rows

        edge_rows = self._handle_edge_query(normalized_query, params)
        if edge_rows is not None:
            return edge_rows

        return []

    def _is_schema_query(self, normalized_query: str) -> bool:
        return (
            "create table if not exists memories" in normalized_query
            or "create table if not exists edges" in normalized_query
        )

    def _handle_memory_query(
        self,
        normalized_query: str,
        params: tuple[object, ...],
    ) -> list[tuple[object, ...]] | None:
        if "insert into memories" in normalized_query:
            memory_id = str(params[0])
            payload = str(params[1])
            self.memories[memory_id] = payload
            return []

        if "select payload from memories where memory_id" in normalized_query:
            memory_id = str(params[0])
            payload = self.memories.get(memory_id)
            return [(payload,)] if payload is not None else []

        if "select payload from memories order by memory_id" in normalized_query:
            return [(payload,) for _, payload in sorted(self.memories.items())]

        return None

    def _handle_edge_query(
        self,
        normalized_query: str,
        params: tuple[object, ...],
    ) -> list[tuple[object, ...]] | None:
        if "insert into edges" in normalized_query:
            edge_id = str(params[0])
            source_id = str(params[1])
            target_id = str(params[2])
            payload = str(params[3])
            self.edges[edge_id] = (source_id, target_id, payload)
            return []

        if self._is_edge_neighbor_query(normalized_query):
            memory_id = str(params[0])
            rows = []
            for _, (source_id, target_id, payload) in sorted(self.edges.items()):
                if source_id == memory_id or target_id == memory_id:
                    rows.append((payload,))
            return rows

        if "from edges order by edge_id" in normalized_query:
            return [(payload,) for _, (_, _, payload) in sorted(self.edges.items())]

        return None

    def _is_edge_neighbor_query(self, normalized_query: str) -> bool:
        return "from edges" in normalized_query and "where source_id" in normalized_query


class _FakeSQLConnection:
    def __init__(self, engine: _FakeSQLEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeSQLConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    def execute(
        self,
        query: str,
        params: Sequence[object] = (),
    ) -> _FakeSQLResult:
        rows = self._engine.execute(query, params)
        return _FakeSQLResult(rows)

    def executemany(self, query: str, rows: Sequence[tuple[object, ...]]) -> None:
        for row in rows:
            self._engine.execute(query, row)


class _FakeMySQLCursor:
    def __init__(self, engine: _FakeSQLEngine) -> None:
        self._engine = engine
        self._rows: list[tuple[object, ...]] = []

    def execute(self, query: str, params: Sequence[object] = ()) -> _FakeMySQLCursor:
        self._rows = self._engine.execute(query, params)
        return self

    def executemany(self, query: str, rows: Sequence[tuple[object, ...]]) -> None:
        for row in rows:
            self._engine.execute(query, row)

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

    def close(self) -> None:
        self._rows = []


class _FakeMySQLConnection:
    def __init__(self, engine: _FakeSQLEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeMySQLConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    def close(self) -> None:
        return None

    def cursor(self) -> _FakeMySQLCursor:
        return _FakeMySQLCursor(self._engine)


def _install_duckdb(monkeypatch: pytest.MonkeyPatch, engine: _FakeSQLEngine) -> None:
    module = ModuleType("duckdb")
    module.connect = lambda _: _FakeSQLConnection(engine)
    monkeypatch.setitem(sys.modules, "duckdb", module)


def _install_postgresql(monkeypatch: pytest.MonkeyPatch, engine: _FakeSQLEngine) -> None:
    module = ModuleType("psycopg")
    module.connect = lambda *_: _FakeSQLConnection(engine)
    monkeypatch.setitem(sys.modules, "psycopg", module)


def _install_mysql(monkeypatch: pytest.MonkeyPatch, engine: _FakeSQLEngine) -> None:
    connector_module = ModuleType("mysql.connector")
    connector_module.connect = lambda **_: _FakeMySQLConnection(engine)
    mysql_module = ModuleType("mysql")
    mysql_module.connector = connector_module
    monkeypatch.setitem(sys.modules, "mysql", mysql_module)
    monkeypatch.setitem(sys.modules, "mysql.connector", connector_module)


@pytest.mark.parametrize(
    "label,memory_cls,graph_cls,backend_id,install_driver",
    [
        ("duckdb", DuckDBMemoryStore, DuckDBGraphStore, "cellin.duckdb", _install_duckdb),
        (
            "postgresql",
            PostgreSQLMemoryStore,
            PostgreSQLGraphStore,
            "postgresql://cellin/test",
            _install_postgresql,
        ),
        (
            "mysql",
            MySQLMemoryStore,
            MySQLGraphStore,
            "mysql://cellin:test@localhost:3306/cellin",
            _install_mysql,
        ),
    ],
)
def test_sql_backends_share_memory_store_and_filter_archived_edges(
    label: str,
    memory_cls: type,
    graph_cls: type,
    backend_id: str,
    install_driver: Callable[[pytest.MonkeyPatch, _FakeSQLEngine], None],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql_backends._BACKENDS.clear()
    engine = _FakeSQLEngine()
    install_driver(monkeypatch, engine)

    active = _edge("edge-active", "memory-1", "memory-2", archived=False)
    archived = _edge("edge-archived", "memory-1", "memory-3", archived=True)
    support_memory = _memory("support-memory", "Support memory")

    connection_key = str((tmp_path / backend_id).resolve()) if label == "duckdb" else backend_id
    memory_store = memory_cls(connection_key)
    graph_store = graph_cls(connection_key)
    initial_create_count = len(
        [query for query, _ in engine.queries if "CREATE TABLE IF NOT EXISTS" in query.upper()]
    )

    memory_store.put(_memory("memory-1", "Atlas memory"))
    memory_store.put(_memory("memory-2", "Second memory"))
    memory_store.put_many(())
    graph_store.upsert_edges((active, archived))
    graph_store.upsert_memories((support_memory,))
    graph_store.upsert_edge(active)
    graph_store.upsert_edges(())

    assert memory_store.get("memory-1") == _memory("memory-1", "Atlas memory")
    assert memory_store.get("missing-memory") is None
    assert graph_store.get_memory("memory-1") == _memory("memory-1", "Atlas memory")
    assert graph_store.neighbors("memory-1") == (active,)
    assert graph_store.list_edges() == (active,)
    assert graph_store.shares_memory_store(memory_store)
    assert memory_store.list() == (
        _memory("memory-1", "Atlas memory"),
        _memory("memory-2", "Second memory"),
        _memory("support-memory", "Support memory"),
    )

    # Re-instantiating stores with the same connection should be idempotent and share
    # one initialized schema.
    duplicate_memory_store = memory_cls(connection_key)
    duplicate_graph_store = graph_cls(connection_key)
    duplicate_graph_store.upsert_memory(_memory("memory-1", "Atlas revised"))
    duplicate_memory_store.put(_memory("memory-3", "Third memory"))

    assert duplicate_graph_store.shares_memory_store(duplicate_memory_store)
    assert duplicate_graph_store.shares_memory_store(memory_store)
    assert memory_store.get("memory-1").text == "Atlas revised"

    final_create_count = len(
        [query for query, _ in engine.queries if "CREATE TABLE IF NOT EXISTS" in query.upper()]
    )
    assert final_create_count == initial_create_count
    assert final_create_count == 2
