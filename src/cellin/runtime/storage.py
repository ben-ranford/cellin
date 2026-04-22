"""Storage composition layer for resolved runtime storage backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import dataclass as _dc
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
            role_registry = _BACKEND_REGISTRY[provider.role]
            previous_provider = role_registry.get(provider.backend)
            try:
                register_storage_backends(provider)
            except StorageBackendError:
                # registration is idempotent across process boundaries; ignore repeats
                pass
            else:
                if role_registry.get(provider.backend) is not previous_provider:
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
    if path_value == ":memory__":
        return path_value

    configured_path = Path(path_value)
    resolved_path = (
        configured_path
        if configured_path.is_absolute()
        else (workspace_root / configured_path).resolve()
    )
    return str(resolved_path)


def _resolve_connection_string(
    config: StorageBackendConfig,
    *,
    backend_name: str,
) -> str:
    connection_string = config.database_path
    if not connection_string or not connection_string.strip():
        raise StorageBackendError(f"{backend_name} backend requires a connection string")
    return connection_string


# ---------------------------------------------------------------------------
# Table-driven built-in backend registry
# ---------------------------------------------------------------------------


@_dc(frozen=True)
class _BackendEntry:
    role: StorageRole
    name: str
    factory: Callable[[StorageBackendConfig, Path], object]


# ---------------------------------------------------------------------------
# _BUILTIN_BACKENDS — one row per (role, backend-name) pair.
#
# Each lambda references module-level class names directly so that
# monkeypatching ``cellin.runtime.storage.<ClassName>`` in tests works
# correctly — the name is resolved at call time, not at table-construction
# time.
#
# vector vs. representation divergence:
#   As of this version both roles expose an identical set of backends.
#   The two roles are conceptually distinct (short-term episodic retrieval vs.
#   semantic / embedding-based lookup), but no built-in backend is currently
#   exclusive to one role.  If a future backend should appear in only one role
#   (e.g. a specialised embedding store not suitable for raw memory lookup),
#   add it to the appropriate section below and leave the other role without
#   that entry.  The assertion after the table documents that the current
#   equivalence is intentional and will catch accidental drift.
# ---------------------------------------------------------------------------

_BUILTIN_BACKENDS: list[_BackendEntry] = [
    # -- memory role --------------------------------------------------------
    _BackendEntry(
        "memory",
        "duckdb",
        lambda c, r: DuckDBMemoryStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    _BackendEntry("memory", "in_memory", lambda c, r: InMemoryMemoryStore()),
    _BackendEntry(
        "memory",
        "mongodb",
        lambda c, r: MongoDBMemoryStore(_resolve_connection_string(c, backend_name="mongodb")),
    ),
    _BackendEntry(
        "memory",
        "mysql",
        lambda c, r: MySQLMemoryStore(_resolve_connection_string(c, backend_name="mysql")),
    ),
    _BackendEntry(
        "memory",
        "postgresql",
        lambda c, r: PostgreSQLMemoryStore(
            _resolve_connection_string(c, backend_name="postgresql")
        ),
    ),
    _BackendEntry(
        "memory",
        "redis",
        lambda c, r: RedisMemoryStore(_resolve_connection_string(c, backend_name="redis")),
    ),
    _BackendEntry(
        "memory",
        "sqlite",
        lambda c, r: SQLiteMemoryStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    # -- graph role ---------------------------------------------------------
    _BackendEntry(
        "graph",
        "arangodb",
        lambda c, r: ArangoDBGraphStore(_resolve_connection_string(c, backend_name="arangodb")),
    ),
    _BackendEntry(
        "graph",
        "duckdb",
        lambda c, r: DuckDBGraphStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    _BackendEntry("graph", "in_memory", lambda c, r: InMemoryGraphStore()),
    _BackendEntry(
        "graph",
        "memgraph",
        lambda c, r: MemgraphGraphStore(_resolve_connection_string(c, backend_name="memgraph")),
    ),
    _BackendEntry(
        "graph",
        "mongodb",
        lambda c, r: MongoDBGraphStore(_resolve_connection_string(c, backend_name="mongodb")),
    ),
    _BackendEntry(
        "graph",
        "mysql",
        lambda c, r: MySQLGraphStore(_resolve_connection_string(c, backend_name="mysql")),
    ),
    _BackendEntry(
        "graph",
        "neo4j",
        lambda c, r: Neo4jGraphStore(_resolve_connection_string(c, backend_name="neo4j")),
    ),
    _BackendEntry(
        "graph",
        "postgresql",
        lambda c, r: PostgreSQLGraphStore(_resolve_connection_string(c, backend_name="postgresql")),
    ),
    _BackendEntry(
        "graph",
        "redis",
        lambda c, r: RedisGraphStore(_resolve_connection_string(c, backend_name="redis")),
    ),
    _BackendEntry(
        "graph",
        "sqlite",
        lambda c, r: SQLiteGraphStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    # -- vector role --------------------------------------------------------
    # Intentionally mirrors the representation role exactly (see comment above).
    _BackendEntry("vector", "in_memory_vector_index", lambda c, r: InMemoryVectorIndex()),
    _BackendEntry(
        "vector",
        "milvus",
        lambda c, r: MilvusVectorStore(_resolve_connection_string(c, backend_name="milvus")),
    ),
    _BackendEntry(
        "vector",
        "pgvector",
        lambda c, r: PGVectorStore(_resolve_connection_string(c, backend_name="pgvector")),
    ),
    _BackendEntry(
        "vector",
        "pinecone",
        lambda c, r: PineconeVectorStore(_resolve_connection_string(c, backend_name="pinecone")),
    ),
    _BackendEntry(
        "vector",
        "qdrant",
        lambda c, r: QdrantVectorStore(_resolve_connection_string(c, backend_name="qdrant")),
    ),
    _BackendEntry(
        "vector",
        "redis_vector",
        lambda c, r: RedisVectorStore(_resolve_connection_string(c, backend_name="redis_vector")),
    ),
    _BackendEntry(
        "vector",
        "sqlite_vec",
        lambda c, r: SQLiteVecStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    _BackendEntry(
        "vector",
        "weaviate",
        lambda c, r: WeaviateVectorStore(_resolve_connection_string(c, backend_name="weaviate")),
    ),
    # -- representation role ------------------------------------------------
    # Intentionally mirrors the vector role exactly (see comment above).
    _BackendEntry("representation", "in_memory_vector_index", lambda c, r: InMemoryVectorIndex()),
    _BackendEntry(
        "representation",
        "milvus",
        lambda c, r: MilvusVectorStore(_resolve_connection_string(c, backend_name="milvus")),
    ),
    _BackendEntry(
        "representation",
        "pgvector",
        lambda c, r: PGVectorStore(_resolve_connection_string(c, backend_name="pgvector")),
    ),
    _BackendEntry(
        "representation",
        "pinecone",
        lambda c, r: PineconeVectorStore(_resolve_connection_string(c, backend_name="pinecone")),
    ),
    _BackendEntry(
        "representation",
        "qdrant",
        lambda c, r: QdrantVectorStore(_resolve_connection_string(c, backend_name="qdrant")),
    ),
    _BackendEntry(
        "representation",
        "redis_vector",
        lambda c, r: RedisVectorStore(_resolve_connection_string(c, backend_name="redis_vector")),
    ),
    _BackendEntry(
        "representation",
        "sqlite_vec",
        lambda c, r: SQLiteVecStore(_resolve_database_path(c.database_path, workspace_root=r)),
    ),
    _BackendEntry(
        "representation",
        "weaviate",
        lambda c, r: WeaviateVectorStore(_resolve_connection_string(c, backend_name="weaviate")),
    ),
]

# Assert that vector and representation expose exactly the same backend names.
# This documents that the current equivalence is deliberate (see comment above).
assert {e.name for e in _BUILTIN_BACKENDS if e.role == "vector"} == {
    e.name for e in _BUILTIN_BACKENDS if e.role == "representation"
}, (
    "vector and representation built-in backend sets have diverged; "
    "update the comment block above _BUILTIN_BACKENDS to explain any intentional difference"
)


def _register_builtin_backends() -> None:
    if _BACKEND_REGISTRY["memory"]:
        return

    for entry in _BUILTIN_BACKENDS:
        _f = entry.factory
        register_storage_backends(
            StorageBackendProvider(
                role=entry.role,
                backend=entry.name,
                builder=lambda config, *, workspace_root, _f=_f: _f(config, workspace_root),
            )
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
