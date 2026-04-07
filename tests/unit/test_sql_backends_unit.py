"""Unit tests for low-level SQL backend internals."""

from __future__ import annotations

import builtins

import pytest

from cellin.stores import sql_backends

MYSQL_CONNECTION_URL = "mysql://user:placeholder@localhost:3306/cellin"
MYSQL_PASSWORD = "placeholder"


class _NullResultConnection:
    def __enter__(self) -> _NullResultConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    def execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        del query, parameters
        return None


def test_sql_backend_relational_backend_guard_paths() -> None:
    sql_backends._BACKENDS.clear()
    backend = sql_backends._backend_for(
        "null-backend",
        "null-key",
        lambda: _NullResultConnection(),
        parameter_style="?",
        upsert_memory_sql=sql_backends._DUCKDB_MEMORY_UPSERT_SQL,
        upsert_edge_sql=sql_backends._DUCKDB_EDGE_UPSERT_SQL,
    )

    assert backend.get_memory("absent") is None
    assert backend.list_memories() == ()
    backend.put_memories(())
    backend.upsert_edges(())
    backend._ensure_schema()


def test_sql_backends_build_with_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def _import_with_missing_module(
        name: str,
        import_globals: object | None = None,
        import_locals: object | None = None,
        fromlist: tuple[object, ...] | None = (),
        level: int = 0,
    ) -> object:
        if name in {"duckdb", "psycopg", "mysql"}:
            raise ModuleNotFoundError(f"No module named {name}")
        return original_import(
            name,
            import_globals,
            import_locals,
            fromlist,
            level,
        )

    monkeypatch.setattr(builtins, "__import__", _import_with_missing_module)

    with pytest.raises(
        sql_backends._MissingDuckDBDependencyError,
        match="duckdb backend requires optional dependency",
    ):
        sql_backends._build_duckdb_connection("cellin.duckdb")()

    with pytest.raises(
        sql_backends._MissingPostgreSQLDependencyError,
        match="postgresql backend requires optional dependency",
    ):
        sql_backends._build_postgresql_connection("postgresql://localhost/db")()

    with pytest.raises(
        sql_backends._MissingMySQLDependencyError,
        match="mysql backend requires optional dependency `mysql-connector-python`",
    ):
        sql_backends._build_mysql_connection("mysql://localhost/db")()


def test_parse_mysql_connection_string_and_memory_path_resolution() -> None:
    assert sql_backends._parse_mysql_connection_string(MYSQL_CONNECTION_URL) == (
        sql_backends._MySQLConnectionParams(
            user="user",
            password=MYSQL_PASSWORD,
            host="localhost",
            port=3306,
            database="cellin",
        )
    )

    with pytest.raises(
        ValueError,
        match="mysql backend requires a mysql:// connection string",
    ):
        sql_backends._parse_mysql_connection_string("postgresql://cellin/test")

    assert sql_backends._resolve_file_path(":memory:") == ":memory:"
    assert sql_backends._resolve_file_path("sample.db").endswith("/sample.db")
