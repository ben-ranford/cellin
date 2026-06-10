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

    def find(self, filters: dict[str, object] | None = None) -> list[dict[str, object]]:
        if not filters:
            return [dict(document) for _, document in sorted(self._documents.items())]
        return [
            dict(document)
            for _, document in sorted(self._documents.items())
            if all(str(document.get(name, "")) == str(value) for name, value in filters.items())
        ]


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
def test_graph_native_backends_detect_shared_memory_store_identity(
    graph_cls: type,
    connection_string: str,
    install_backend: Callable[[pytest.MonkeyPatch], None],
    clear_backends: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_backends()
    install_backend(monkeypatch)

    graph_store = graph_cls(connection_string)
    backend = graph_store._backend

    if isinstance(graph_store, ArangoDBGraphStore):
        shared_memory_store = type(
            "_SharedArangoMemoryStore",
            (),
            {
                "_database": backend._database,
                "_connection_info": backend._connection_info,
            },
        )()
        separate_memory_store = type(
            "_SeparateArangoMemoryStore",
            (),
            {
                "_database": object(),
                "_connection_info": graph_backends._ArangoConnectionInfo(
                    "https://other:8529",
                    "other",
                    "root",
                    "test",
                ),
            },
        )()
    else:
        shared_memory_store = type(
            "_SharedCypherMemoryStore",
            (),
            {
                "_driver": backend._driver,
                "_backend_url": backend._backend_url,
            },
        )()
        separate_memory_store = type(
            "_SeparateCypherMemoryStore",
            (),
            {
                "_driver": object(),
                "_backend_url": "bolt://other:7687",
            },
        )()

    assert graph_store.shares_memory_store(shared_memory_store)
    assert not graph_store.shares_memory_store(separate_memory_store)


def test_arangodb_backend_encodes_memory_ids_in_document_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_backends._ARANGO_BACKENDS.clear()
    _install_fake_arango(monkeypatch)

    source_id = "memory/with/slash"
    target_id = "neighbor:with:colon"
    graph_store = ArangoDBGraphStore("arangodb://root:test@localhost:8529/cellin")
    edge = _edge("edge-1", source_id, target_id, archived=False)

    graph_store.upsert_memory(_memory(source_id, "Source"))
    graph_store.upsert_memory(_memory(target_id, "Target"))
    graph_store.upsert_edge(edge)

    backend = graph_store._backend
    assert backend._memory_collection.get("memory%2Fwith%2Fslash") is not None
    assert backend._memory_collection.get(source_id) is None
    assert (
        backend._edge_collection._documents["edge-1"]["_from"]
        == "cellin_memories/memory%2Fwith%2Fslash"
    )
    assert (
        backend._edge_collection._documents["edge-1"]["_to"]
        == "cellin_memories/neighbor%3Awith%3Acolon"
    )
    assert graph_store.get_memory(source_id) == _memory(source_id, "Source")
    assert graph_store.neighbors(source_id) == (edge,)
    assert graph_store.list_edges() == (edge,)


def test_arangodb_backend_neighbors_and_list_edges_do_not_full_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_backends._ARANGO_BACKENDS.clear()
    _install_fake_arango(monkeypatch)

    edge = _edge("edge-2", "memory-1", "memory-2", archived=False)
    graph_store = ArangoDBGraphStore("arangodb://root:test@localhost:8529/cellin")
    graph_store.upsert_memory(_memory("memory-1", "Atlas"))
    graph_store.upsert_memory(_memory("memory-2", "Another"))
    graph_store.upsert_edge(edge)

    backend = graph_store._backend

    def scan_not_expected() -> list[dict[str, object]]:
        raise AssertionError("Edge scan should be filtered, not full-scan")

    monkeypatch.setattr(backend._edge_collection, "all", scan_not_expected)

    assert graph_store.neighbors("memory-1") == (edge,)
    assert graph_store.list_edges() == (edge,)


def test_arangodb_backend_find_edge_documents_falls_back_across_find_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_backends._ARANGO_BACKENDS.clear()
    _install_fake_arango(monkeypatch)

    graph_store = ArangoDBGraphStore("arangodb://root:test@localhost:8529/cellin")
    backend = graph_store._backend
    document = {
        "_key": "edge-find",
        "_from": "cellin_memories/memory-1",
        "_to": "cellin_memories/memory-2",
        "payload": graph_backends.dump_edge(
            _edge("edge-find", "memory-1", "memory-2", archived=False)
        ),
        "archived": False,
    }
    backend._edge_collection.insert(document, overwrite=True)

    def positional_find(filters: dict[str, object] | None = None) -> list[dict[str, object]]:
        if filters is None:
            return [document]
        raise TypeError("filters must be passed by keyword")

    monkeypatch.setattr(backend._edge_collection, "find", positional_find)
    assert backend._find_edge_documents() == [document]

    def keyword_only_find(*args: object, **kwargs: object) -> list[dict[str, object]]:
        assert args == ()
        assert kwargs == {"filters": {"archived": False}}
        return [document]

    monkeypatch.setattr(backend._edge_collection, "find", keyword_only_find)
    assert backend._find_edge_documents({"archived": False}) == [document]

    def broken_find(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        raise TypeError("fallback to scan")

    monkeypatch.setattr(backend._edge_collection, "find", broken_find)
    assert backend._find_edge_documents() == [document]
    assert backend._find_edge_documents({"archived": False}) == [document]


def test_arangodb_backend_filters_duplicate_invalid_and_archived_edge_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_backends._ARANGO_BACKENDS.clear()
    _install_fake_arango(monkeypatch)

    graph_store = ArangoDBGraphStore("arangodb://root:test@localhost:8529/cellin")
    graph_store.upsert_memory(_memory("memory-1", "Atlas"))
    graph_store.upsert_memory(_memory("memory-2", "Neighbor"))
    backend = graph_store._backend

    duplicate_edge = _edge("edge-self", "memory-1", "memory-1", archived=False)
    archived_edge = _edge("edge-archived", "memory-1", "memory-2", archived=True)

    backend._edge_collection.insert(
        {
            "_key": duplicate_edge.edge_id,
            "_from": "cellin_memories/memory-1",
            "_to": "cellin_memories/memory-1",
            "payload": graph_backends.dump_edge(duplicate_edge),
            "archived": False,
        },
        overwrite=True,
    )
    backend._edge_collection.insert(
        {
            "_key": "edge-invalid",
            "_from": "cellin_memories/memory-1",
            "_to": "cellin_memories/memory-2",
            "payload": {"unexpected": True},
            "archived": False,
        },
        overwrite=True,
    )
    backend._edge_collection.insert(
        {
            "_key": archived_edge.edge_id,
            "_from": "cellin_memories/memory-1",
            "_to": "cellin_memories/memory-2",
            "payload": graph_backends.dump_edge(archived_edge),
            "archived": False,
        },
        overwrite=True,
    )

    assert graph_store.neighbors("memory-1") == (duplicate_edge,)
    assert graph_store.list_edges() == (duplicate_edge,)


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
