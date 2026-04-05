"""Graph-native backends for Neo4j, Memgraph, and ArangoDB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlparse

from cellin.core import GraphStore, MemoryAtom, MemoryEdge
from cellin.stores._graph_serialization import (
    dump_edge,
    dump_memory,
    edge_is_archived,
    load_edge,
    load_memory,
)

_MEMORY_CONSTRAINT_CYPHER = """
CREATE CONSTRAINT cellin_memory_id IF NOT EXISTS
FOR (memory:CellinMemory)
REQUIRE memory.memory_id IS UNIQUE
"""

_UPSERT_MEMORY_CYPHER = """
MERGE (memory:CellinMemory {memory_id: $memory_id})
SET memory.payload = $payload, memory.archived = $archived
"""

_UPSERT_EDGE_CYPHER = """
MERGE (source:CellinMemory {memory_id: $source_id})
MERGE (target:CellinMemory {memory_id: $target_id})
MERGE (source)-[edge:CELLIN_EDGE {edge_id: $edge_id}]->(target)
SET edge.payload = $payload, edge.archived = $archived
"""

_GET_MEMORY_CYPHER = """
MATCH (memory:CellinMemory {memory_id: $memory_id})
RETURN memory.payload AS payload
"""

_NEIGHBOR_EDGES_CYPHER = """
MATCH (:CellinMemory {memory_id: $memory_id})-[edge:CELLIN_EDGE]-(:CellinMemory)
WHERE coalesce(edge.archived, false) = false
RETURN edge.payload AS payload
ORDER BY edge.edge_id
"""

_LIST_EDGES_CYPHER = """
MATCH ()-[edge:CELLIN_EDGE]->()
WHERE coalesce(edge.archived, false) = false
RETURN edge.payload AS payload
ORDER BY edge.edge_id
"""


class _Neo4jResult(Protocol):
    def data(self) -> list[dict[str, object]]: ...


class _Neo4jSession(Protocol):
    def __enter__(self) -> _Neo4jSession: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(self, query: str, **parameters: object) -> _Neo4jResult: ...


class _Neo4jDriver(Protocol):
    def session(self) -> _Neo4jSession: ...


class _ArangoCollection(Protocol):
    def insert(self, document: dict[str, object], *, overwrite: bool = False) -> object: ...

    def get(self, key: str) -> dict[str, object] | None: ...

    def all(self) -> list[dict[str, object]]: ...


class _ArangoDatabase(Protocol):
    def has_collection(self, name: str) -> bool: ...

    def create_collection(self, name: str, *, edge: bool = False) -> object: ...

    def collection(self, name: str) -> _ArangoCollection: ...


class _MissingNeo4jDependencyError(RuntimeError):
    """Raised when the Neo4j-compatible dependency is unavailable."""


class _MissingArangoDependencyError(RuntimeError):
    """Raised when the ArangoDB dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class _ArangoConnectionInfo:
    hosts: str
    database: str
    username: str | None
    password: str | None


def _parse_arango_connection_string(connection_string: str) -> _ArangoConnectionInfo:
    parsed = urlparse(connection_string)
    if parsed.scheme not in {"arangodb", "http", "https"}:
        raise ValueError("arangodb backend requires an arangodb://, http://, or https:// URL")

    scheme = "https" if parsed.scheme == "https" else "http"
    host = parsed.hostname or "localhost"
    port = parsed.port or 8529
    database = parsed.path.strip("/") or "_system"

    return _ArangoConnectionInfo(
        hosts=f"{scheme}://{host}:{port}",
        database=database,
        username=parsed.username,
        password=parsed.password,
    )


def _load_optional_payload(payload: object) -> MemoryAtom | None:
    if payload is None:
        return None
    if not isinstance(payload, str):
        raise TypeError("graph backend payloads must be strings")
    return load_memory(payload)


class _CypherGraphBackend:
    """Shared Neo4j/Memgraph graph operations."""

    def __init__(self, connection_string: str, *, backend_name: str) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingNeo4jDependencyError(
                f"{backend_name} backend requires optional dependency `neo4j`"
            ) from exc

        parsed = urlparse(connection_string)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError(
                f"{backend_name} backend requires a valid bolt-style connection string"
            )

        uri = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 7687}"
        auth = None
        if parsed.username is not None:
            auth = (parsed.username, parsed.password or "")

        self._driver = cast(_Neo4jDriver, GraphDatabase.driver(uri, auth=auth))
        self._ensure_schema()

    def _run(self, query: str, **parameters: object) -> list[dict[str, object]]:
        with self._driver.session() as active_session:
            result = active_session.run(query, **parameters)
            data = result.data()
        return list(data)

    def _ensure_schema(self) -> None:
        self._run(_MEMORY_CONSTRAINT_CYPHER)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._run(
            _UPSERT_MEMORY_CYPHER,
            memory_id=memory.memory_id,
            payload=dump_memory(memory),
            archived=memory.decay.archived,
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        rows = self._run(_GET_MEMORY_CYPHER, memory_id=memory_id)
        if not rows:
            return None
        return _load_optional_payload(rows[0].get("payload"))

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._run(
            _UPSERT_EDGE_CYPHER,
            edge_id=edge.edge_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            payload=dump_edge(edge),
            archived=edge_is_archived(edge),
        )

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for row in self._run(_NEIGHBOR_EDGES_CYPHER, memory_id=memory_id)
            if (edge := load_edge(cast(str, row["payload"]))) and not edge_is_archived(edge)
        )

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(
            edge
            for row in self._run(_LIST_EDGES_CYPHER)
            if (edge := load_edge(cast(str, row["payload"]))) and not edge_is_archived(edge)
        )


class _ArangoGraphBackend:
    """ArangoDB graph operations using document and edge collections."""

    def __init__(self, connection_string: str) -> None:
        try:
            from arango import ArangoClient  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise _MissingArangoDependencyError(
                "arangodb backend requires optional dependency `python-arango`"
            ) from exc

        connection = _parse_arango_connection_string(connection_string)
        client = ArangoClient(hosts=connection.hosts)
        database = cast(
            _ArangoDatabase,
            client.db(
                connection.database,
                username=connection.username,
                password=connection.password,
            ),
        )
        self._database = database
        self._ensure_collections()
        self._memory_collection = database.collection("cellin_memories")
        self._edge_collection = database.collection("cellin_edges")

    def _ensure_collections(self) -> None:
        if not self._database.has_collection("cellin_memories"):
            self._database.create_collection("cellin_memories")
        if not self._database.has_collection("cellin_edges"):
            self._database.create_collection("cellin_edges", edge=True)

    def _ensure_memory_placeholder(self, memory_id: str) -> None:
        if self._memory_collection.get(memory_id) is None:
            self._memory_collection.insert(
                {"_key": memory_id, "memory_id": memory_id, "payload": None},
                overwrite=True,
            )

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._memory_collection.insert(
            {
                "_key": memory.memory_id,
                "memory_id": memory.memory_id,
                "payload": dump_memory(memory),
                "archived": memory.decay.archived,
            },
            overwrite=True,
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        document = self._memory_collection.get(memory_id)
        if document is None:
            return None
        return _load_optional_payload(document.get("payload"))

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._ensure_memory_placeholder(edge.source_id)
        self._ensure_memory_placeholder(edge.target_id)
        self._edge_collection.insert(
            {
                "_key": edge.edge_id,
                "_from": f"cellin_memories/{edge.source_id}",
                "_to": f"cellin_memories/{edge.target_id}",
                "payload": dump_edge(edge),
                "archived": edge_is_archived(edge),
            },
            overwrite=True,
        )

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        edges = []
        for document in self._edge_collection.all():
            payload = document.get("payload")
            if not isinstance(payload, str):
                continue
            edge = load_edge(payload)
            if edge_is_archived(edge):
                continue
            if edge.source_id == memory_id or edge.target_id == memory_id:
                edges.append(edge)
        return tuple(sorted(edges, key=lambda edge: edge.edge_id))

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        edges = []
        for document in self._edge_collection.all():
            payload = document.get("payload")
            if not isinstance(payload, str):
                continue
            edge = load_edge(payload)
            if not edge_is_archived(edge):
                edges.append(edge)
        return tuple(sorted(edges, key=lambda edge: edge.edge_id))


_NEO4J_BACKENDS: dict[str, _CypherGraphBackend] = {}
_MEMGRAPH_BACKENDS: dict[str, _CypherGraphBackend] = {}
_ARANGO_BACKENDS: dict[str, _ArangoGraphBackend] = {}


def _neo4j_backend(connection_string: str) -> _CypherGraphBackend:
    backend = _NEO4J_BACKENDS.get(connection_string)
    if backend is None:
        backend = _CypherGraphBackend(connection_string, backend_name="neo4j")
        _NEO4J_BACKENDS[connection_string] = backend
    return backend


def _memgraph_backend(connection_string: str) -> _CypherGraphBackend:
    backend = _MEMGRAPH_BACKENDS.get(connection_string)
    if backend is None:
        backend = _CypherGraphBackend(connection_string, backend_name="memgraph")
        _MEMGRAPH_BACKENDS[connection_string] = backend
    return backend


def _arangodb_backend(connection_string: str) -> _ArangoGraphBackend:
    backend = _ARANGO_BACKENDS.get(connection_string)
    if backend is None:
        backend = _ArangoGraphBackend(connection_string)
        _ARANGO_BACKENDS[connection_string] = backend
    return backend


class Neo4jGraphStore(GraphStore):
    """GraphStore backed by Neo4j relationships and node payload snapshots."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _CypherGraphBackend | None = None,
    ) -> None:
        self._backend = _backend or _neo4j_backend(connection_string)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.upsert_memory(memory)

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        for memory in memories:
            self._backend.upsert_memory(memory)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edge(edge)

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        for edge in edges:
            self._backend.upsert_edge(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()


class MemgraphGraphStore(GraphStore):
    """GraphStore backed by Memgraph via the Neo4j-compatible driver."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _CypherGraphBackend | None = None,
    ) -> None:
        self._backend = _backend or _memgraph_backend(connection_string)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.upsert_memory(memory)

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        for memory in memories:
            self._backend.upsert_memory(memory)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edge(edge)

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        for edge in edges:
            self._backend.upsert_edge(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()


class ArangoDBGraphStore(GraphStore):
    """GraphStore backed by ArangoDB document and edge collections."""

    def __init__(
        self,
        connection_string: str,
        *,
        _backend: _ArangoGraphBackend | None = None,
    ) -> None:
        self._backend = _backend or _arangodb_backend(connection_string)

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.upsert_memory(memory)

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        for memory in memories:
            self._backend.upsert_memory(memory)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._backend.upsert_edge(edge)

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        for edge in edges:
            self._backend.upsert_edge(edge)

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
