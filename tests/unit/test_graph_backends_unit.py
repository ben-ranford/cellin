"""Unit tests for graph-native backend helpers."""

from __future__ import annotations

import builtins
import sys

import pytest

from cellin.stores import graph_backends

NEO4J_CONNECTION_URL = "bolt://neo4j:placeholder@localhost:7687"
ARANGO_CONNECTION_URL = "arangodb://root:placeholder@localhost:8529/cellin"
ARANGO_PASSWORD = "placeholder"


def test_graph_backends_require_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _missing_backend(
        name: str,
        globals: object | None = None,
        locals: object | None = None,
        fromlist: tuple[object, ...] | None = (),
        level: int = 0,
    ) -> object:
        if name in {"neo4j", "arango"}:
            raise ModuleNotFoundError(f"No module named {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "neo4j", raising=False)
    monkeypatch.delitem(sys.modules, "arango", raising=False)
    monkeypatch.setattr(builtins, "__import__", _missing_backend)

    with pytest.raises(
        graph_backends._MissingNeo4jDependencyError,
        match="neo4j backend requires optional dependency `neo4j`",
    ):
        graph_backends._CypherGraphBackend(
            NEO4J_CONNECTION_URL,
            backend_name="neo4j",
        )

    with pytest.raises(
        graph_backends._MissingArangoDependencyError,
        match="arangodb backend requires optional dependency `python-arango`",
    ):
        graph_backends._ArangoGraphBackend(ARANGO_CONNECTION_URL)


def test_parse_arango_connection_string_defaults_and_validation() -> None:
    assert graph_backends._parse_arango_connection_string(
        ARANGO_CONNECTION_URL
    ) == graph_backends._ArangoConnectionInfo(
        hosts="http://localhost:8529",
        database="cellin",
        username="root",
        password=ARANGO_PASSWORD,
    )

    assert graph_backends._parse_arango_connection_string("https://localhost") == (
        graph_backends._ArangoConnectionInfo(
            hosts="https://localhost:8529",
            database="_system",
            username=None,
            password=None,
        )
    )

    with pytest.raises(ValueError, match="arangodb backend requires"):
        graph_backends._parse_arango_connection_string("postgresql://cellin/test")
