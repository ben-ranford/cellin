"""Storage composition layer for resolved runtime storage backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
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
DEFAULT_STORAGE_ENTRYPOINT_GROUP = "cellin.storage"


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


class StorageBackendSetup(Protocol):
    """Optional explicit setup hook used by CLI operations."""

    def __call__(
        self,
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StorageBackendProvider:
    """Runtime registry contract for pluggable storage backends."""

    role: StorageRole
    backend: str
    builder: BackendBuilder
    setup: StorageBackendSetup | None = None


_BACKEND_REGISTRY: dict[StorageRole, dict[str, StorageBackendProvider]] = {
    "memory": {},
    "graph": {},
    "vector": {},
    "representation": {},
}


def _normalize_role(role: str) -> StorageRole:
    normalized = role.lower()
    if normalized not in {"graph", "memory", "representation", "vector"}:
        raise StorageBackendError(f"Unknown storage role: {role}")
    return cast(StorageRole, normalized)


def _coerce_backend_name(raw: str) -> str:
    normalized = raw.strip()
    if not normalized:
        raise StorageBackendError("Storage backend names must not be blank.")
    return normalized


def register_storage_backends(*providers: StorageBackendProvider) -> None:
    """Register storage providers with the runtime boundary."""

    for provider in providers:
        role_registry = _BACKEND_REGISTRY[_normalize_role(provider.role)]
        backend_name = _coerce_backend_name(provider.backend)
        existing = role_registry.get(backend_name)
        if existing is provider or (
            existing is not None
            and existing.role == provider.role
            and existing.builder is provider.builder
            and existing.setup is provider.setup
        ):
            continue
        if existing is not None:
            raise StorageBackendError(
                f"Storage backend `{backend_name}` already registered for role `{provider.role}`"
            )
        role_registry[backend_name] = StorageBackendProvider(
            role=provider.role,
            backend=backend_name,
            builder=provider.builder,
            setup=provider.setup,
        )


def list_storage_backends(role: StorageRole | None = None) -> tuple[StorageBackendProvider, ...]:
    """List registered backends in registration order for each role."""

    _register_builtin_backends()

    if role is not None:
        role_registry = _BACKEND_REGISTRY[_normalize_role(role)]
        return tuple(role_registry.values())

    providers: list[StorageBackendProvider] = []
    for role in ("memory", "graph", "vector", "representation"):
        providers.extend(_BACKEND_REGISTRY[cast(StorageRole, role)].values())
    return tuple(providers)


def _coerce_provider(raw: object) -> tuple[StorageBackendProvider, ...]:
    if isinstance(raw, StorageBackendProvider):
        return (raw,)

    if isinstance(raw, (tuple, list)):
        providers: list[StorageBackendProvider] = []
        for item in raw:
            providers.extend(_coerce_provider(item))
        return tuple(providers)

    raise TypeError(
        "Storage backend entry points must yield `StorageBackendProvider`, "
        "a tuple of them, or an equivalent sequence."
    )


def _load_storage_backend_provider_target(loaded: object) -> tuple[StorageBackendProvider, ...]:
    should_instantiate = isinstance(loaded, type) or (
        callable(loaded) and not isinstance(loaded, StorageBackendProvider)
    )
    candidate = cast(Callable[[], object], loaded)() if should_instantiate else loaded
    return _coerce_provider(candidate)


def load_storage_backends_from_entry_points(
    *,
    entrypoint_group: str = DEFAULT_STORAGE_ENTRYPOINT_GROUP,
) -> tuple[str, ...]:
    """Discover additional storage providers from entry points."""

    selected = metadata.entry_points().select(group=entrypoint_group)
    loaded: list[str] = []

    for entry_point in selected:
        providers = _load_storage_backend_provider_target(entry_point.load())

        for provider in providers:
            try:
                register_storage_backends(provider)
            except StorageBackendError:
                # registration is idempotent across process boundaries; ignore repeats
                pass
            loaded.append(f"{provider.role}:{provider.backend}")

    return tuple(loaded)


def initialize_storage_backends(
    *,
    load_entry_points: bool = True,
    entrypoint_group: str = DEFAULT_STORAGE_ENTRYPOINT_GROUP,
) -> tuple[str, ...]:
    """Initialize built-in providers and optionally discover entry-point backends."""

    _register_builtin_backends()
    if not load_entry_points:
        return ()
    return load_storage_backends_from_entry_points(entrypoint_group=entrypoint_group)


def _resolve_backend(
    role: StorageRole,
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> object:
    role_registry = _BACKEND_REGISTRY[role]
    provider = role_registry.get(config.backend)
    if provider is None:
        raise StorageBackendError(f"Unknown backend `{config.backend}` for role `{role}`")
    return provider.builder(config, workspace_root=workspace_root)


def setup_storage_backends(
    storage: StorageConfig,
    *,
    workspace_root: Path,
    include_roles: tuple[StorageRole, ...] | None = None,
    backend_filter: str | None = None,
    dry_run: bool = False,
) -> tuple[tuple[StorageRole, str], ...]:
    """Run explicit setup for selected durable backends."""

    initialize_storage_backends()

    targets: tuple[tuple[StorageRole, StorageBackendConfig], ...] = (
        ("memory", storage.memory),
        ("graph", storage.graph),
        ("vector", storage.vector),
        ("representation", storage.representation),
    )

    selected_roles = set(include_roles or ("memory", "graph", "vector", "representation"))
    resolved: list[tuple[StorageRole, str]] = []

    for role, config in targets:
        if role not in selected_roles:
            continue
        if backend_filter is not None and config.backend != backend_filter:
            continue

        provider = _BACKEND_REGISTRY[role].get(config.backend)
        if provider is None:
            raise StorageBackendError(f"Unknown backend `{config.backend}` for role `{role}`")

        if not dry_run:
            if provider.setup is None:
                provider.builder(config, workspace_root=workspace_root)
            else:
                provider.setup(config, workspace_root=workspace_root)
        resolved.append((role, config.backend))

    return tuple(resolved)


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


def _register_builtin_backends() -> None:
    if _BACKEND_REGISTRY["memory"]:
        return

    register_storage_backends(
        StorageBackendProvider(role="memory", backend="duckdb", builder=_build_duckdb_memory_store),
        StorageBackendProvider(role="memory", backend="mysql", builder=_build_mysql_memory_store),
        StorageBackendProvider(role="memory", backend="sqlite", builder=_build_sqlite_memory_store),
        StorageBackendProvider(
            role="memory", backend="in_memory", builder=_build_in_memory_memory_store
        ),
        StorageBackendProvider(
            role="memory", backend="postgresql", builder=_build_postgresql_memory_store
        ),
        StorageBackendProvider(
            role="memory", backend="mongodb", builder=_build_mongodb_memory_store
        ),
        StorageBackendProvider(role="memory", backend="redis", builder=_build_redis_memory_store),
    )

    register_storage_backends(
        StorageBackendProvider(
            role="graph", backend="arangodb", builder=_build_arangodb_graph_store
        ),
        StorageBackendProvider(role="graph", backend="duckdb", builder=_build_duckdb_graph_store),
        StorageBackendProvider(
            role="graph", backend="in_memory", builder=_build_in_memory_graph_store
        ),
        StorageBackendProvider(
            role="graph", backend="memgraph", builder=_build_memgraph_graph_store
        ),
        StorageBackendProvider(role="graph", backend="mongodb", builder=_build_mongodb_graph_store),
        StorageBackendProvider(role="graph", backend="mysql", builder=_build_mysql_graph_store),
        StorageBackendProvider(role="graph", backend="neo4j", builder=_build_neo4j_graph_store),
        StorageBackendProvider(
            role="graph", backend="postgresql", builder=_build_postgresql_graph_store
        ),
        StorageBackendProvider(role="graph", backend="redis", builder=_build_redis_graph_store),
        StorageBackendProvider(role="graph", backend="sqlite", builder=_build_sqlite_graph_store),
    )

    register_storage_backends(
        StorageBackendProvider(
            role="vector", backend="in_memory_vector_index", builder=_build_vector_store
        ),
        StorageBackendProvider(
            role="vector", backend="sqlite_vec", builder=_build_sqlite_vec_store
        ),
        StorageBackendProvider(role="vector", backend="pgvector", builder=_build_pgvector_store),
        StorageBackendProvider(role="vector", backend="pinecone", builder=_build_pinecone_store),
        StorageBackendProvider(role="vector", backend="qdrant", builder=_build_qdrant_store),
        StorageBackendProvider(role="vector", backend="weaviate", builder=_build_weaviate_store),
        StorageBackendProvider(role="vector", backend="milvus", builder=_build_milvus_store),
        StorageBackendProvider(
            role="vector", backend="redis_vector", builder=_build_redis_vector_store
        ),
    )

    register_storage_backends(
        StorageBackendProvider(
            role="representation",
            backend="in_memory_vector_index",
            builder=_build_vector_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="sqlite_vec",
            builder=_build_sqlite_vec_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="pgvector",
            builder=_build_pgvector_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="pinecone",
            builder=_build_pinecone_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="qdrant",
            builder=_build_qdrant_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="weaviate",
            builder=_build_weaviate_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="milvus",
            builder=_build_milvus_store,
        ),
        StorageBackendProvider(
            role="representation",
            backend="redis_vector",
            builder=_build_redis_vector_store,
        ),
    )


def build_storage_bundle(
    storage: StorageConfig,
    *,
    workspace_root: Path,
) -> StorageBundle:
    """Resolve role configs to concrete storage objects."""

    initialize_storage_backends()

    memory_store = cast(
        MemoryStore,
        _resolve_backend(
            "memory",
            storage.memory,
            workspace_root=workspace_root,
        ),
    )
    graph_store = cast(
        GraphStore,
        _resolve_backend(
            "graph",
            storage.graph,
            workspace_root=workspace_root,
        ),
    )
    vector_store = cast(
        VectorStore,
        _resolve_backend(
            "vector",
            storage.vector,
            workspace_root=workspace_root,
        ),
    )
    representation_store = cast(
        VectorStore,
        _resolve_backend(
            "representation",
            storage.representation,
            workspace_root=workspace_root,
        ),
    )

    return StorageBundle(
        memory_store=memory_store,
        graph_store=graph_store,
        vector_store=vector_store,
        representation_store=representation_store,
    )


__all__ = [
    "DEFAULT_STORAGE_ENTRYPOINT_GROUP",
    "StorageBackendConfig",
    "StorageBackendError",
    "StorageBackendProvider",
    "StorageBackendSetup",
    "StorageConfig",
    "StorageRole",
    "StorageBundle",
    "build_storage_bundle",
    "initialize_storage_backends",
    "list_storage_backends",
    "load_storage_backends_from_entry_points",
    "register_storage_backends",
    "setup_storage_backends",
]
