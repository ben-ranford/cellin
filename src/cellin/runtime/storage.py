"""Storage composition layer for resolved runtime storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from cellin.core import GraphStore, MemoryStore, VectorStore
from cellin.stores import InMemoryVectorIndex, SQLiteGraphStore, SQLiteMemoryStore

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
        """Return a config that keeps SQLite for graph/memory and in-memory vector roles."""

        sqlite_backend = StorageBackendConfig("sqlite", database_path)
        vector_backend = StorageBackendConfig("in_memory_vector_index")
        return cls(
            memory=sqlite_backend,
            graph=sqlite_backend,
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
        raise StorageBackendError("SQLite backend requires a `database_path` value")

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
    database_path = _resolve_database_path(config.database_path, workspace_root=workspace_root)
    return SQLiteMemoryStore(database_path)


def _build_sqlite_graph_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> GraphStore:
    database_path = _resolve_database_path(config.database_path, workspace_root=workspace_root)
    return SQLiteGraphStore(database_path)


def _build_vector_store(
    config: StorageBackendConfig,
    *,
    workspace_root: Path,
) -> VectorStore:
    # Vector stores are in-memory only for now, so no backend-local workspace
    # resolution is required. Keep the signature consistent with other builders.
    del config, workspace_root
    return InMemoryVectorIndex()


_MEMORY_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "sqlite": _build_sqlite_memory_store,
}


_GRAPH_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "sqlite": _build_sqlite_graph_store,
}


_VECTOR_BACKEND_REGISTRY: dict[str, BackendBuilder] = {
    "in_memory_vector_index": _build_vector_store,
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
