"""Integration coverage for graph-native Neo4j, Memgraph, and ArangoDB backends."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from cellin.dreaming import ContradictionRepairDreamStrategy, DreamRunner
from cellin.retrieval import RetrievalCandidateGenerator
from cellin.stores import (
    ArangoDBGraphStore,
    InMemoryMemoryStore,
    MemgraphGraphStore,
    Neo4jGraphStore,
    graph_backends,
)


def _memory(
    memory_id: str,
    text: str,
    *,
    topic: str = "atlas",
    observed_at: datetime | None = None,
) -> MemoryAtom:
    now = observed_at or datetime(2026, 4, 5, tzinfo=UTC)
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
        metadata={"topic": topic},
    )


def _edge(edge_id: str, source_id: str, target_id: str, *, archived: bool) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        metadata={"archived": archived},
    )


class _FakeNeo4jResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def data(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeNeo4jSession:
    def __init__(self, state: dict[str, dict[str, object]]) -> None:
        self._state = state

    def __enter__(self) -> _FakeNeo4jSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    def run(self, query: str, **params: object) -> _FakeNeo4jResult:
        normalized = " ".join(query.lower().split())
        memories = self._state["memories"]
        edges = self._state["edges"]

        if "create constraint" in normalized:
            return _FakeNeo4jResult([])

        if "set memory.payload" in normalized:
            memories[str(params["memory_id"])] = {
                "payload": params["payload"],
                "archived": params["archived"],
            }
            return _FakeNeo4jResult([])

        if "return memory.payload as payload" in normalized:
            document = memories.get(str(params["memory_id"]))
            if document is None:
                return _FakeNeo4jResult([])
            return _FakeNeo4jResult([{"payload": document.get("payload")}])

        if "set edge.payload" in normalized:
            memories.setdefault(str(params["source_id"]), {"payload": None})
            memories.setdefault(str(params["target_id"]), {"payload": None})
            edges[str(params["edge_id"])] = {
                "payload": params["payload"],
                "archived": params["archived"],
            }
            return _FakeNeo4jResult([])

        if "match (:cellinmemory {memory_id: $memory_id})-[edge:cellin_edge]" in normalized:
            memory_id = str(params["memory_id"])
            rows = []
            for document in edges.values():
                payload = str(document["payload"])
                edge = graph_backends.load_edge(payload)
                if edge.source_id == memory_id or edge.target_id == memory_id:
                    rows.append({"payload": payload})
            return _FakeNeo4jResult(rows)

        if "match ()-[edge:cellin_edge]->()" in normalized:
            return _FakeNeo4jResult(
                [{"payload": str(document["payload"])} for _, document in sorted(edges.items())]
            )

        raise AssertionError(f"Unexpected cypher query: {query}")


class _FakeNeo4jDriver:
    def __init__(self) -> None:
        self.state = {"memories": {}, "edges": {}}

    def session(self) -> _FakeNeo4jSession:
        return _FakeNeo4jSession(self.state)


class _FakeArangoCollection:
    def __init__(self) -> None:
        self._documents: dict[str, dict[str, object]] = {}

    def insert(self, document: dict[str, object], *, overwrite: bool = False) -> None:
        del overwrite
        self._documents[str(document["_key"])] = dict(document)

    def get(self, key: str) -> dict[str, object] | None:
        document = self._documents.get(key)
        return dict(document) if document is not None else None

    def all(self) -> list[dict[str, object]]:
        return [dict(document) for _, document in sorted(self._documents.items())]


class _FakeArangoDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeArangoCollection] = {}

    def has_collection(self, name: str) -> bool:
        return name in self._collections

    def create_collection(self, name: str, *, edge: bool = False) -> None:
        del edge
        self._collections[name] = _FakeArangoCollection()

    def collection(self, name: str) -> _FakeArangoCollection:
        return self._collections[name]


class _FakeArangoClient:
    def __init__(self) -> None:
        self._databases: dict[str, _FakeArangoDatabase] = {}

    def db(self, name: str, username: str | None, password: str | None) -> _FakeArangoDatabase:
        del username, password
        database = self._databases.get(name)
        if database is None:
            database = _FakeArangoDatabase()
            self._databases[name] = database
        return database


def _install_fake_neo4j(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = _FakeNeo4jDriver()

    class _GraphDatabase:
        @staticmethod
        def driver(*_args, **_kwargs) -> _FakeNeo4jDriver:
            return driver

    module = ModuleType("neo4j")
    module.GraphDatabase = _GraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", module)


def _install_fake_arango(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeArangoClient()

    class _ArangoClientFactory:
        def __init__(self, *, hosts: str) -> None:
            del hosts

        def db(
            self,
            name: str,
            username: str | None,
            password: str | None,
        ) -> _FakeArangoDatabase:
            return client.db(name, username, password)

    module = ModuleType("arango")
    module.ArangoClient = _ArangoClientFactory
    monkeypatch.setitem(sys.modules, "arango", module)


@pytest.mark.parametrize(
    "graph_cls,connection_string,install_backend,clear_backends",
    [
        (
            Neo4jGraphStore,
            "bolt://neo4j:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._NEO4J_BACKENDS.clear,
        ),
        (
            MemgraphGraphStore,
            "bolt://memgraph:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._MEMGRAPH_BACKENDS.clear,
        ),
        (
            ArangoDBGraphStore,
            "arangodb://root:test@localhost:8529/cellin",
            _install_fake_arango,
            graph_backends._ARANGO_BACKENDS.clear,
        ),
    ],
)
def test_graph_native_backends_filter_archived_edges_and_share_state(
    graph_cls: type,
    connection_string: str,
    install_backend: Callable[[pytest.MonkeyPatch], None],
    clear_backends: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_backends()
    install_backend(monkeypatch)

    graph_store = graph_cls(connection_string)
    duplicate_graph_store = graph_cls(connection_string)
    active = _edge("edge-active", "memory-1", "memory-2", archived=False)
    archived = _edge("edge-archived", "memory-1", "memory-3", archived=True)

    graph_store.upsert_memory(_memory("memory-1", "Atlas memory"))
    graph_store.upsert_memory(_memory("memory-2", "Second memory"))
    graph_store.upsert_edges((active, archived))
    duplicate_graph_store.upsert_memory(_memory("memory-1", "Atlas revised"))

    assert graph_store.get_memory("memory-1") == _memory("memory-1", "Atlas revised")
    assert graph_store.get_memory("missing-memory") is None
    assert graph_store.neighbors("memory-1") == (active,)
    assert graph_store.list_edges() == (active,)


@pytest.mark.parametrize(
    "graph_cls,connection_string,install_backend,clear_backends",
    [
        (
            Neo4jGraphStore,
            "bolt://neo4j:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._NEO4J_BACKENDS.clear,
        ),
        (
            MemgraphGraphStore,
            "bolt://memgraph:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._MEMGRAPH_BACKENDS.clear,
        ),
        (
            ArangoDBGraphStore,
            "arangodb://root:test@localhost:8529/cellin",
            _install_fake_arango,
            graph_backends._ARANGO_BACKENDS.clear,
        ),
    ],
)
def test_graph_native_backends_support_candidate_generation_with_memory_fallback(
    graph_cls: type,
    connection_string: str,
    install_backend: Callable[[pytest.MonkeyPatch], None],
    clear_backends: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_backends()
    install_backend(monkeypatch)

    seed = _memory("seed", "Atlas retrieval graph")
    neighbor = _memory("neighbor", "Completely unrelated memory")
    graph_store = graph_cls(connection_string)
    graph_store.upsert_memory(seed)
    graph_store.upsert_edge(_edge("seed-neighbor", "seed", "neighbor", archived=False))
    memory_store = InMemoryMemoryStore((seed, neighbor))

    collected = RetrievalCandidateGenerator(
        memory_store=memory_store,
        graph_store=graph_store,
    ).collect("Atlas retrieval", limit=2)

    assert tuple(memory.memory_id for memory in collected) == ("seed", "neighbor")
    assert graph_store.get_memory("neighbor") is None
    assert collected[1].metadata["graph_distance"] == 1


@pytest.mark.parametrize(
    "graph_cls,connection_string,install_backend,clear_backends",
    [
        (
            Neo4jGraphStore,
            "bolt://neo4j:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._NEO4J_BACKENDS.clear,
        ),
        (
            MemgraphGraphStore,
            "bolt://memgraph:test@localhost:7687",
            _install_fake_neo4j,
            graph_backends._MEMGRAPH_BACKENDS.clear,
        ),
        (
            ArangoDBGraphStore,
            "arangodb://root:test@localhost:8529/cellin",
            _install_fake_arango,
            graph_backends._ARANGO_BACKENDS.clear,
        ),
    ],
)
def test_graph_native_backends_support_dream_runner_and_rollback(
    graph_cls: type,
    connection_string: str,
    install_backend: Callable[[pytest.MonkeyPatch], None],
    clear_backends: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_backends()
    install_backend(monkeypatch)

    now = datetime(2026, 4, 5, tzinfo=UTC)
    older = _memory(
        "atlas-green",
        "Atlas rollout is green and stable in staging.",
        topic="atlas-rollout",
        observed_at=now - timedelta(days=2),
    )
    newer = _memory(
        "atlas-rollback",
        "Atlas rollout was rolled back after failures in staging.",
        topic="atlas-rollout",
        observed_at=now - timedelta(days=1),
    )
    memory_store = InMemoryMemoryStore((older, newer))
    graph_store = graph_cls(connection_string)
    graph_store.upsert_memories((older, newer))
    runner = DreamRunner(
        graph_store=graph_store,
        memory_store=memory_store,
        strategies={"contradiction_repair": ContradictionRepairDreamStrategy()},
    )

    result = runner.run_strategy("contradiction_repair", at=now)

    assert result is not None
    assert graph_store.list_edges()[0].kind is EdgeKind.CONTRADICTS

    runner.rollback(result.diff)

    assert graph_store.list_edges() == ()
