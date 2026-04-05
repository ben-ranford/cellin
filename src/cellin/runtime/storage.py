"""Storage composition layer for resolved runtime storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from cellin.core import GraphStore, MemoryStore, VectorStore
from cellin.stores import (
    ArangoDBGraphStore,
    DuckDBGraphStore,
    DuckDBMemoryStore,
    InMemoryGraphStore,
    InMemoryMemoryStore,
    InMemoryVectorIndex,
    MemgraphGraphStore,
    MilvusVectorStore,
    MongoDBGraphStore,
    MongoDBMemoryStore,
    MySQLGraphStore,
    MySQLMemoryStore,
    Neo4jGraphStore,
    PGVectorStore,
    PineconeVectorStore,
    PostgreSQLGraphStore,
    PostgreSQLMemoryStore,
    QdrantVectorStore,
    RedisGraphStore,
    RedisMemoryStore,
    RedisVectorStore,
    SQLiteGraphStore,
    SQLiteMemoryStore,
    SQLiteVecStore,
    WeaviateVectorStore,
)

StorageRole = Literal["graph", "memory", "representation", "vector"]


class StorageBackendError(ValueError):
    """Raised when a storage role uses an unknown backend family."""


@dataclass(frozen=True, slots=True)
class StorageBackendConfig:
    """Backend selector and minimal role-specific options."""

    backend: str
    database_path: str | None = None


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Role-specific storage composition for runtime initialization."""

    memory: StorageBackendConfig
    graph: StorageBackendConfig
    vector: StorageBackendConfig
    representation: StorageBackendConfig

    @classmethod
    def with_sqlite_preset(cls, database_path: str) -> StorageConfig:
        """Return an explicit, sqlite-backed storage preset."""

        sqlite_backend = StorageBackendConfig("sqlite", database_path)
        vector_backend = StorageBackendConfig("in_memory_vector_index")
        return cls(
            memory=sqlite_backend,
            graph=sqlite_backend,
            vector=vector_backend,
            representation=vector_backend,
        )

    @classmethod
    def with_in_memory_preset(cls) -> StorageConfig:
        """Return the batteries-included in-memory storage preset."""

        in_memory_backend = StorageBackendConfig("in_memory")
        vector_backend = StorageBackendConfig("in_memory_vector_index")
        return cls(
            memory=in_memory_backend,
            graph=in_memory_backend,
            vector=vector_backend,
            representation=vector_backend,
        )


@dataclass(frozen=True, slots=True)
class StorageBundle:
    """Concrete storage objects produced by backend resolution."""

    memory_store: MemoryStore
    graph_store: GraphStore
    vector_store: VectorStore
    representation_store: VectorStore


class BackendBuilder(Protocol):
    """Callable that resolves one storage backend configuration."""

    def __call__(
        self,
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> object: ...


__all__ = [
    "StorageBackendConfig",
    "StorageBackendError",
    "StorageConfig",
    "StorageBundle",
    "build_storage_bundle",
]


def _resolve_database_path(path_value: str | None, *, workspace_root: Path) -> str:
    if path_value is None:
        raise StorageBackendError("`database_path` is required for this backend")

    configured_path = Path(path_value)
    resolved_path = (
        configured_path
        if configured_path.is_absolute()
        else (workspace_root / configured_path).resolve()
    )
    return str(resolved_path)


def _build_sqlite_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    database_path = _resolve_database_path(
        config.database_path,
        workspace_root=workspace_root,
    )
    return SQLiteMemoryStore(database_path)


def _build_sqlite_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    database_path = _resolve_database_path(
        config.database_path,
        workspace_root=workspace_root,
    )
    return SQLiteGraphStore(database_path)


def _resolve_connection_string(
    config: StorageBackendConfig,
    *,
    backend_name: str,
) -> str:
    connection_string = config.database_path
    if not connection_string:
        raise StorageBackendError(f"{backend_name} backend requires a connection string")
    return connection_string


def _build_duckdb_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    database_path = _resolve_database_path(
        config.database_path,
        workspace_root=workspace_root,
    )
    return DuckDBMemoryStore(database_path)


def _build_duckdb_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    database_path = _resolve_database_path(
        config.database_path,
        workspace_root=workspace_root,
    )
    return DuckDBGraphStore(database_path)


def _build_postgresql_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    del workspace_root
    return PostgreSQLMemoryStore(_resolve_connection_string(config, backend_name="postgresql"))


def _build_postgresql_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return PostgreSQLGraphStore(_resolve_connection_string(config, backend_name="postgresql"))


def _build_mysql_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    del workspace_root
    return MySQLMemoryStore(_resolve_connection_string(config, backend_name="mysql"))


def _build_mysql_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return MySQLGraphStore(_resolve_connection_string(config, backend_name="mysql"))


def _build_in_memory_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    del config, workspace_root
    return InMemoryMemoryStore()


def _build_in_memory_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del config, workspace_root
    return InMemoryGraphStore()


def _build_mongodb_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    del workspace_root
    return MongoDBMemoryStore(_resolve_connection_string(config, backend_name="mongodb"))


def _build_mongodb_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return MongoDBGraphStore(_resolve_connection_string(config, backend_name="mongodb"))


def _build_redis_memory_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> MemoryStore:
    del workspace_root
    return RedisMemoryStore(_resolve_connection_string(config, backend_name="redis"))


def _build_redis_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return RedisGraphStore(_resolve_connection_string(config, backend_name="redis"))


def _build_neo4j_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return Neo4jGraphStore(_resolve_connection_string(config, backend_name="neo4j"))


def _build_memgraph_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return MemgraphGraphStore(_resolve_connection_string(config, backend_name="memgraph"))


def _build_arangodb_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    del workspace_root
    return ArangoDBGraphStore(_resolve_connection_string(config, backend_name="arangodb"))


def _build_vector_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del config, workspace_root
    return InMemoryVectorIndex()


def _build_sqlite_vec_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    database_path = _resolve_database_path(
        config.database_path,
        workspace_root=workspace_root,
    )
    return SQLiteVecStore(database_path)


def _build_pgvector_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    connection_string = config.database_path
    if connection_string is None:
        raise StorageBackendError("pgvector backend requires a connection string")
    return PGVectorStore(connection_string)


def _build_pinecone_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    return PineconeVectorStore(_resolve_connection_string(config, backend_name="pinecone"))


def _build_qdrant_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    return QdrantVectorStore(_resolve_connection_string(config, backend_name="qdrant"))


def _build_weaviate_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    return WeaviateVectorStore(_resolve_connection_string(config, backend_name="weaviate"))


def _build_milvus_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    return MilvusVectorStore(_resolve_connection_string(config, backend_name="milvus"))


def _build_redis_vector_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    del workspace_root
    return RedisVectorStore(_resolve_connection_string(config, backend_name="redis_vector"))


_MEMORY_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "duckdb": _build_duckdb_memory_store,
    "mysql": _build_mysql_memory_store,
    "sqlite": _build_sqlite_memory_store,
    "postgresql": _build_postgresql_memory_store,
    "in_memory": _build_in_memory_memory_store,
    "mongodb": _build_mongodb_memory_store,
    "redis": _build_redis_memory_store,
}


_GRAPH_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "arangodb": _build_arangodb_graph_store,
    "duckdb": _build_duckdb_graph_store,
    "in_memory": _build_in_memory_graph_store,
    "memgraph": _build_memgraph_graph_store,
    "mongodb": _build_mongodb_graph_store,
    "mysql": _build_mysql_graph_store,
    "neo4j": _build_neo4j_graph_store,
    "postgresql": _build_postgresql_graph_store,
    "redis": _build_redis_graph_store,
    "sqlite": _build_sqlite_graph_store,
}


_VECTOR_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "in_memory_vector_index": _build_vector_store,
    "sqlite_vec": _build_sqlite_vec_store,
    "pgvector": _build_pgvector_store,
    "pinecone": _build_pinecone_store,
    "qdrant": _build_qdrant_store,
    "weaviate": _build_weaviate_store,
    "milvus": _build_milvus_store,
    "redis_vector": _build_redis_vector_store,
}


def _resolve_backend(
    role: StorageRole,
    config: StorageBackendConfig,
    *,
    backend_registry: dict[str, BackendBuilder],
    workspace_root: Path,
) -> object:
    builder = backend_registry.get(config.backend)
    if builder is None:
        raise StorageBackendError(f"Unknown backend `{config.backend}` for role `{role}`")
    return builder(config, workspace_root=workspace_root)


def build_storage_bundle(
    storage: StorageConfig,
    *,
    workspace_root: Path,
) -> StorageBundle:
    """Resolve role configs to concrete storage objects."""

    memory_store = cast(
        MemoryStore,
        _resolve_backend(
            "memory",
            storage.memory,
            backend_registry=_MEMORY_BACKEND_REGISTRY,
            workspace_root=workspace_root,
        ),
    )
    graph_store = cast(
        GraphStore,
        _resolve_backend(
            "graph",
            storage.graph,
            backend_registry=_GRAPH_BACKEND_REGISTRY,
            workspace_root=workspace_root,
        ),
    )
    vector_store = cast(
        VectorStore,
        _resolve_backend(
            "vector",
            storage.vector,
            backend_registry=_VECTOR_BACKEND_REGISTRY,
            workspace_root=workspace_root,
        ),
    )
    representation_store = cast(
        VectorStore,
        _resolve_backend(
            "representation",
            storage.representation,
            backend_registry=_VECTOR_BACKEND_REGISTRY,
            workspace_root=workspace_root,
        ),
    )

    return StorageBundle(
        memory_store=memory_store,
        graph_store=graph_store,
        vector_store=vector_store,
        representation_store=representation_store,
    )
