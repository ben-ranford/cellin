"""Unit tests for graph-native backend helpers."""

from __future__ import annotations

import builtins
import json
import sys
from datetime import UTC, datetime

import pytest

from cellin.core import (
    EdgeKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
)
from cellin.stores import _graph_serialization, graph_backends

NEO4J_CONNECTION_URL = "bolt://neo4j:placeholder@localhost:7687"
ARANGO_CONNECTION_URL = "arangodb://root:placeholder@localhost:8529/cellin"
ARANGO_CREDENTIAL = "placeholder"


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
        password=ARANGO_CREDENTIAL,
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


def test_load_memory_rejects_invalid_provenance_metadata_shape() -> None:
    memory = MemoryAtom(
        memory_id="memory-1",
        kind=MemoryKind.ATOM,
        text="Atlas memory",
        provenance=Provenance(source_id="memory-1", source_type="fixture"),
        modality=Modality.TEXT,
        created_at=datetime(2026, 4, 8, tzinfo=UTC),
        observed_at=datetime(2026, 4, 8, tzinfo=UTC),
        metadata={},
    )
    payload = json.loads(_graph_serialization.dump_memory(memory))
    payload["provenance"]["metadata"] = ["not", "a", "mapping"]

    with pytest.raises(TypeError, match="provenance.metadata payload must be a mapping"):
        _graph_serialization.load_memory(json.dumps(payload))


@pytest.mark.parametrize("half_life_days", [None, "missing"])
def test_load_memory_accepts_optional_half_life_days(
    half_life_days: None | str,
) -> None:
    memory = MemoryAtom(
        memory_id="memory-1",
        kind=MemoryKind.ATOM,
        text="Atlas memory",
        provenance=Provenance(source_id="memory-1", source_type="fixture"),
        modality=Modality.TEXT,
        created_at=datetime(2026, 4, 8, tzinfo=UTC),
        observed_at=datetime(2026, 4, 8, tzinfo=UTC),
        metadata={},
    )
    payload = json.loads(_graph_serialization.dump_memory(memory))
    if half_life_days == "missing":
        payload["decay"].pop("half_life_days", None)
    else:
        payload["decay"]["half_life_days"] = half_life_days

    loaded = _graph_serialization.load_memory(json.dumps(payload))
    assert loaded.decay.half_life_days is None


def test_neo4j_and_memgraph_are_cypher_wrapper_instances() -> None:
    from cellin.stores.graph_backends import (
        MemgraphGraphStore,
        Neo4jGraphStore,
        _CypherGraphStoreWrapper,
    )

    assert issubclass(Neo4jGraphStore, _CypherGraphStoreWrapper)
    assert issubclass(MemgraphGraphStore, _CypherGraphStoreWrapper)


def test_load_edge_rejects_invalid_provenance_metadata_shape() -> None:
    edge = MemoryEdge(
        edge_id="edge-1",
        source_id="memory-1",
        target_id="memory-2",
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id="edge-1", source_type="fixture"),
        created_at=datetime(2026, 4, 8, tzinfo=UTC),
        metadata={},
    )
    payload = json.loads(_graph_serialization.dump_edge(edge))
    payload["provenance"]["metadata"] = 0

    with pytest.raises(TypeError, match="provenance.metadata payload must be a mapping"):
        _graph_serialization.load_edge(json.dumps(payload))
