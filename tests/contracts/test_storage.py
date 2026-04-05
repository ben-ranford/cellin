"""Tests for workspace storage configuration migration and backend resolution."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

import cellin.runtime.storage as runtime_storage
from cellin.cli.config import load_workspace
from cellin.runtime.storage import (
    StorageBackendConfig,
    StorageBackendError,
    StorageBackendProvider,
    StorageConfig,
    build_storage_bundle,
    list_storage_backends,
    load_storage_backends_from_entry_points,
    register_storage_backends,
    setup_storage_backends,
)
from cellin.stores import (
    ArangoDBGraphStore,
    DuckDBGraphStore,
    DuckDBMemoryStore,
    MemgraphGraphStore,
    MilvusVectorStore,
    MongoDBGraphStore,
    MongoDBMemoryStore,
    MySQLGraphStore,
    MySQLMemoryStore,
    Neo4jGraphStore,
    PineconeVectorStore,
    PostgreSQLGraphStore,
    PostgreSQLMemoryStore,
    QdrantVectorStore,
    RedisGraphStore,
    RedisMemoryStore,
    RedisVectorStore,
    SQLiteMemoryStore,
    SQLiteVecStore,
    WeaviateVectorStore,
)


@pytest.fixture
def storage_registry_snapshot() -> Iterator[None]:
    snapshot = {
        role: dict(providers) for role, providers in runtime_storage._BACKEND_REGISTRY.items()
    }
    yield
    for role, providers in runtime_storage._BACKEND_REGISTRY.items():
        providers.clear()
        providers.update(snapshot[role])


@dataclass
class _FakeStorageEntryPoint:
    name: str
    group: str
    loaded: object

    def load(self) -> object:
        return self.loaded


class _FakeStorageEntryPoints(list[_FakeStorageEntryPoint]):
    def select(self, *, group: str) -> list[_FakeStorageEntryPoint]:
        return [entry_point for entry_point in self if entry_point.group == group]


def test_load_workspace_migrates_legacy_database_path(tmp_path: Path) -> None:
    config_path = tmp_path / "legacy.json"
    config_path.write_text(
        json.dumps(
            {
                "runtime_id": "legacy-workspace",
                "database_path": "legacy.sqlite",
                "trace_path": "legacy-traces.jsonl",
                "profile_name": "balanced",
            }
        ),
        encoding="utf-8",
    )

    workspace = load_workspace(config_path)

    assert workspace.runtime_id == "legacy-workspace"
    assert workspace.storage == StorageConfig.with_sqlite_preset("legacy.sqlite")
    assert workspace.trace_path == (tmp_path / "legacy-traces.jsonl").resolve()


def test_load_workspace_uses_role_specific_storage_definition(tmp_path: Path) -> None:
    config_path = tmp_path / "role-specific.json"
    config_path.write_text(
        json.dumps(
            {
                "runtime_id": "role-workspace",
                "trace_path": "trace.jsonl",
                "storage": {
                    "memory": {"backend": "sqlite", "database_path": "memory.sqlite"},
                    "graph": {"backend": "sqlite", "database_path": "graph.sqlite"},
                    "vector": {"backend": "in_memory_vector_index"},
                    "representation": {"backend": "in_memory_vector_index"},
                },
            }
        ),
        encoding="utf-8",
    )

    workspace = load_workspace(config_path)

    assert workspace.runtime_id == "role-workspace"
    assert workspace.storage == StorageConfig(
        memory=StorageBackendConfig("sqlite", "memory.sqlite"),
        graph=StorageBackendConfig("sqlite", "graph.sqlite"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )


def test_build_storage_bundle_rejects_unknown_backend(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("sqlite", "cellin.sqlite"),
        graph=StorageBackendConfig("sqlite", "cellin.sqlite"),
        vector=StorageBackendConfig("no_such_backend"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="NoSuchBackend|no_such_backend"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_list_storage_backends_exposes_builtin_providers() -> None:
    providers = list_storage_backends("memory")
    backends = {provider.backend for provider in providers}

    assert {"duckdb", "in_memory", "sqlite"}.issubset(backends)


def test_list_storage_backends_without_role_returns_all_roles() -> None:
    providers = list_storage_backends()
    roles = {provider.role for provider in providers}

    assert roles == {"memory", "graph", "vector", "representation"}


def test_register_storage_backends_rejects_unknown_role(storage_registry_snapshot: None) -> None:
    with pytest.raises(StorageBackendError, match="Unknown storage role"):
        register_storage_backends(
            StorageBackendProvider(
                role="unknown",  # type: ignore[arg-type]
                backend="invalid_role_backend",
                builder=lambda config, *, workspace_root: (config, workspace_root),
            )
        )


def test_register_storage_backends_rejects_blank_backend_names(
    storage_registry_snapshot: None,
) -> None:
    with pytest.raises(StorageBackendError, match="must not be blank"):
        register_storage_backends(
            StorageBackendProvider(
                role="memory",
                backend="   ",
                builder=lambda config, *, workspace_root: (config, workspace_root),
            )
        )


def test_register_storage_backends_allows_re_registering_same_provider_instance(
    storage_registry_snapshot: None,
) -> None:
    provider = StorageBackendProvider(
        role="memory",
        backend="same_instance_backend",
        builder=lambda config, *, workspace_root: (config, workspace_root),
    )

    register_storage_backends(provider)
    register_storage_backends(provider)

    matching_backends = [
        item.backend
        for item in list_storage_backends("memory")
        if item.backend == "same_instance_backend"
    ]

    assert matching_backends == ["same_instance_backend"]


def test_register_storage_backends_supports_custom_provider_resolution(
    storage_registry_snapshot: None,
    tmp_path: Path,
) -> None:
    class _CustomMemoryStore:
        def __init__(self, connection_string: str) -> None:
            self.connection_string = connection_string

        def put(self, memory: object) -> None:
            del memory

        def get(self, memory_id: str) -> None:
            del memory_id
            return None

        def list(self) -> tuple[object, ...]:
            return ()

    def _build_custom_memory_store(
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> _CustomMemoryStore:
        del workspace_root
        return _CustomMemoryStore(config.database_path or "")

    register_storage_backends(
        StorageBackendProvider(
            role="memory",
            backend="unit_test_memory",
            builder=_build_custom_memory_store,
        )
    )

    bundle = build_storage_bundle(
        StorageConfig(
            memory=StorageBackendConfig("unit_test_memory", "custom://memory"),
            graph=StorageBackendConfig("in_memory"),
            vector=StorageBackendConfig("in_memory_vector_index"),
            representation=StorageBackendConfig("in_memory_vector_index"),
        ),
        workspace_root=tmp_path,
    )

    assert isinstance(bundle.memory_store, _CustomMemoryStore)
    assert bundle.memory_store.connection_string == "custom://memory"


def test_load_storage_backends_from_entry_points_registers_providers(
    storage_registry_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _EntryPointMemoryStore:
        def __init__(self, marker: str) -> None:
            self.marker = marker

        def put(self, memory: object) -> None:
            del memory

        def get(self, memory_id: str) -> None:
            del memory_id
            return None

        def list(self) -> tuple[object, ...]:
            return ()

    def _build_entrypoint_memory_store(
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> _EntryPointMemoryStore:
        del workspace_root
        return _EntryPointMemoryStore(config.database_path or "loaded")

    provider = StorageBackendProvider(
        role="memory",
        backend="entrypoint_memory",
        builder=_build_entrypoint_memory_store,
    )

    monkeypatch.setattr(
        runtime_storage.metadata,
        "entry_points",
        lambda: _FakeStorageEntryPoints(
            [
                _FakeStorageEntryPoint(
                    name="entrypoint-memory",
                    group=runtime_storage.DEFAULT_STORAGE_ENTRYPOINT_GROUP,
                    loaded=lambda: provider,
                )
            ]
        ),
    )

    loaded = load_storage_backends_from_entry_points()
    bundle = build_storage_bundle(
        StorageConfig(
            memory=StorageBackendConfig("entrypoint_memory", "from-entrypoint"),
            graph=StorageBackendConfig("in_memory"),
            vector=StorageBackendConfig("in_memory_vector_index"),
            representation=StorageBackendConfig("in_memory_vector_index"),
        ),
        workspace_root=tmp_path,
    )

    assert loaded == ("memory:entrypoint_memory",)
    assert isinstance(bundle.memory_store, _EntryPointMemoryStore)
    assert bundle.memory_store.marker == "from-entrypoint"


def test_load_storage_backends_from_entry_points_supports_provider_sequences(
    storage_registry_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_one = StorageBackendProvider(
        role="memory",
        backend="sequence_memory_one",
        builder=lambda config, *, workspace_root: (config, workspace_root),
    )
    provider_two = StorageBackendProvider(
        role="graph",
        backend="sequence_graph_two",
        builder=lambda config, *, workspace_root: (config, workspace_root),
    )

    monkeypatch.setattr(
        runtime_storage.metadata,
        "entry_points",
        lambda: _FakeStorageEntryPoints(
            [
                _FakeStorageEntryPoint(
                    name="sequence-providers",
                    group=runtime_storage.DEFAULT_STORAGE_ENTRYPOINT_GROUP,
                    loaded=lambda: (provider_one, [provider_two]),
                )
            ]
        ),
    )

    loaded = load_storage_backends_from_entry_points()

    assert loaded == ("memory:sequence_memory_one", "graph:sequence_graph_two")


def test_load_storage_backends_from_entry_points_rejects_invalid_targets(
    storage_registry_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_storage.metadata,
        "entry_points",
        lambda: _FakeStorageEntryPoints(
            [
                _FakeStorageEntryPoint(
                    name="invalid-provider",
                    group=runtime_storage.DEFAULT_STORAGE_ENTRYPOINT_GROUP,
                    loaded=lambda: "invalid",
                )
            ]
        ),
    )

    with pytest.raises(TypeError, match="Storage backend entry points"):
        load_storage_backends_from_entry_points()


def test_initialize_storage_backends_can_skip_entry_point_loading(
    storage_registry_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = False

    def _record_load(
        *,
        entrypoint_group: str = runtime_storage.DEFAULT_STORAGE_ENTRYPOINT_GROUP,
    ) -> tuple[str, ...]:
        del entrypoint_group
        nonlocal loaded
        loaded = True
        return ("memory:unexpected",)

    monkeypatch.setattr(runtime_storage, "load_storage_backends_from_entry_points", _record_load)

    assert runtime_storage.initialize_storage_backends(load_entry_points=False) == ()
    assert loaded is False


def test_setup_storage_backends_respects_role_and_dry_run_filters(
    storage_registry_snapshot: None,
    tmp_path: Path,
) -> None:
    setup_calls: list[str] = []

    class _SetupMemoryStore:
        def put(self, memory: object) -> None:
            del memory

        def get(self, memory_id: str) -> None:
            del memory_id
            return None

        def list(self) -> tuple[object, ...]:
            return ()

    def _build_setup_memory_store(
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> _SetupMemoryStore:
        del config, workspace_root
        return _SetupMemoryStore()

    def _setup_memory_backend(
        config: StorageBackendConfig,
        *,
        workspace_root: Path,
    ) -> None:
        setup_calls.append(f"{config.backend}@{workspace_root}")

    register_storage_backends(
        StorageBackendProvider(
            role="memory",
            backend="setup_test_memory",
            builder=_build_setup_memory_store,
            setup=_setup_memory_backend,
        )
    )

    storage = StorageConfig(
        memory=StorageBackendConfig("setup_test_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    planned = setup_storage_backends(
        storage,
        workspace_root=tmp_path,
        include_roles=("memory",),
        dry_run=True,
    )
    resolved = setup_storage_backends(
        storage,
        workspace_root=tmp_path,
        include_roles=("memory",),
        dry_run=False,
    )

    assert planned == (("memory", "setup_test_memory"),)
    assert resolved == (("memory", "setup_test_memory"),)
    assert setup_calls == [f"setup_test_memory@{tmp_path}"]


def test_setup_storage_backends_returns_no_matches_when_backend_filter_skips_all_roles(
    storage_registry_snapshot: None,
    tmp_path: Path,
) -> None:
    storage = StorageConfig(
        memory=StorageBackendConfig("in_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    assert setup_storage_backends(storage, workspace_root=tmp_path, backend_filter="sqlite") == ()


def test_setup_storage_backends_rejects_unknown_selected_backend(
    storage_registry_snapshot: None,
    tmp_path: Path,
) -> None:
    storage = StorageConfig(
        memory=StorageBackendConfig("missing_setup_backend"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="missing_setup_backend"):
        setup_storage_backends(storage, workspace_root=tmp_path, include_roles=("memory",))


def test_build_storage_bundle_resolves_sqlite_vec_backend(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("sqlite", "cellin.sqlite"),
        graph=StorageBackendConfig("sqlite", "cellin.sqlite"),
        vector=StorageBackendConfig("sqlite_vec", "vectors.sqlite"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.vector_store, SQLiteVecStore)
    bundle.vector_store.upsert("memory-1", "Atlas architecture and memory graphs")
    assert bundle.vector_store.search("Atlas architecture", limit=1)[0].memory_id == "memory-1"


def test_build_storage_bundle_rejects_sqlite_vec_without_path(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("sqlite", "cellin.sqlite"),
        graph=StorageBackendConfig("sqlite", "cellin.sqlite"),
        vector=StorageBackendConfig("sqlite_vec"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="database_path|SQLite"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_resolves_pgvector_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _FakePGVectorStore:
        def __init__(self, connection_string: str) -> None:
            self.connection_string = connection_string

    monkeypatch.setattr("cellin.runtime.storage.PGVectorStore", _FakePGVectorStore)
    config = StorageConfig(
        memory=StorageBackendConfig("in_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig("pgvector", "postgresql://cellin/test"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.vector_store, _FakePGVectorStore)
    assert bundle.vector_store.connection_string == "postgresql://cellin/test"


@pytest.mark.parametrize(
    ("backend_name", "backend_class"),
    [
        ("pinecone", PineconeVectorStore),
        ("qdrant", QdrantVectorStore),
        ("weaviate", WeaviateVectorStore),
        ("milvus", MilvusVectorStore),
        ("redis_vector", RedisVectorStore),
    ],
)
def test_build_storage_bundle_resolves_remote_vector_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backend_name: str,
    backend_class: type,
) -> None:
    class _FakeVectorStore:
        def __init__(self, connection_string: str) -> None:
            self.connection_string = connection_string

        def upsert(self, memory_id: str, text: str) -> None:
            del memory_id, text

        def search(self, query: str, *, limit: int = 5) -> tuple[object, ...]:
            del query, limit
            return ()

        def delete(self, memory_id: str) -> None:
            del memory_id

    monkeypatch.setattr(
        f"cellin.runtime.storage.{backend_class.__name__}",
        _FakeVectorStore,
    )
    connection_string = f"{backend_name}://localhost:1234/collection"
    config = StorageConfig(
        memory=StorageBackendConfig("in_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig(backend_name, connection_string),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.vector_store, _FakeVectorStore)
    assert bundle.vector_store.connection_string == connection_string


@pytest.mark.parametrize(
    "backend_name",
    ["pinecone", "qdrant", "weaviate", "milvus", "redis_vector"],
)
def test_build_storage_bundle_rejects_remote_vector_backends_without_connection_string(
    tmp_path: Path,
    backend_name: str,
) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("in_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig(backend_name),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(
        StorageBackendError,
        match=f"{backend_name} backend requires a connection string",
    ):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_resolves_duckdb_backends_and_backend_shares_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_backend = object()

    class _FakeDuckDBMemoryStore(DuckDBMemoryStore):
        def __init__(self, database_path: str) -> None:
            self._database_path = database_path
            self._backend = shared_backend

    class _FakeDuckDBGraphStore(DuckDBGraphStore):
        def __init__(self, database_path: str) -> None:
            self._database_path = database_path
            self._backend = shared_backend

    monkeypatch.setattr("cellin.runtime.storage.DuckDBMemoryStore", _FakeDuckDBMemoryStore)
    monkeypatch.setattr("cellin.runtime.storage.DuckDBGraphStore", _FakeDuckDBGraphStore)

    config = StorageConfig(
        memory=StorageBackendConfig("duckdb", "local.duckdb"),
        graph=StorageBackendConfig("duckdb", "local.duckdb"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.memory_store, _FakeDuckDBMemoryStore)
    assert isinstance(bundle.graph_store, _FakeDuckDBGraphStore)
    assert isinstance(bundle.graph_store._backend, object)
    assert bundle.graph_store.shares_memory_store(bundle.memory_store)
    assert bundle.memory_store._database_path == str((tmp_path / "local.duckdb").resolve())


def test_build_storage_bundle_resolves_postgresql_memory_graph_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_backend = object()

    class _FakePostgreSQLMemoryStore(PostgreSQLMemoryStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    class _FakePostgreSQLGraphStore(PostgreSQLGraphStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    monkeypatch.setattr("cellin.runtime.storage.PostgreSQLMemoryStore", _FakePostgreSQLMemoryStore)
    monkeypatch.setattr("cellin.runtime.storage.PostgreSQLGraphStore", _FakePostgreSQLGraphStore)

    connection_string = "postgresql://cellin/test"
    config = StorageConfig(
        memory=StorageBackendConfig("postgresql", connection_string),
        graph=StorageBackendConfig("postgresql", connection_string),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.memory_store, _FakePostgreSQLMemoryStore)
    assert isinstance(bundle.graph_store, _FakePostgreSQLGraphStore)
    assert bundle.memory_store._connection_string == connection_string
    assert bundle.graph_store.shares_memory_store(bundle.memory_store)


def test_build_storage_bundle_resolves_mysql_memory_graph_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_backend = object()

    class _FakeMySQLMemoryStore(MySQLMemoryStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    class _FakeMySQLGraphStore(MySQLGraphStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    monkeypatch.setattr("cellin.runtime.storage.MySQLMemoryStore", _FakeMySQLMemoryStore)
    monkeypatch.setattr("cellin.runtime.storage.MySQLGraphStore", _FakeMySQLGraphStore)

    connection_string = "mysql://cellin:test@localhost:3306/cellin"
    config = StorageConfig(
        memory=StorageBackendConfig("mysql", connection_string),
        graph=StorageBackendConfig("mysql", connection_string),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.memory_store, _FakeMySQLMemoryStore)
    assert isinstance(bundle.graph_store, _FakeMySQLGraphStore)
    assert bundle.memory_store._connection_string == connection_string
    assert bundle.graph_store.shares_memory_store(bundle.memory_store)


def test_build_storage_bundle_rejects_pgvector_without_connection_string(
    tmp_path: Path,
) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("in_memory"),
        graph=StorageBackendConfig("in_memory"),
        vector=StorageBackendConfig("pgvector"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="pgvector backend requires a connection string"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_rejects_postgresql_without_connection_string(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("postgresql"),
        graph=StorageBackendConfig("postgresql"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    with pytest.raises(
        StorageBackendError,
        match="postgresql backend requires a connection string",
    ):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_rejects_mysql_without_connection_string(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("mysql"),
        graph=StorageBackendConfig("mysql"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    with pytest.raises(StorageBackendError, match="mysql backend requires a connection string"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_rejects_duckdb_without_database_path(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("duckdb"),
        graph=StorageBackendConfig("duckdb"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )
    with pytest.raises(StorageBackendError, match="database_path"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_resolves_mongodb_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_backend = object()

    class _FakeMongoMemoryStore(MongoDBMemoryStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    class _FakeMongoGraphStore(MongoDBGraphStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    monkeypatch.setattr("cellin.runtime.storage.MongoDBMemoryStore", _FakeMongoMemoryStore)
    monkeypatch.setattr("cellin.runtime.storage.MongoDBGraphStore", _FakeMongoGraphStore)
    config = StorageConfig(
        memory=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
        graph=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.memory_store, _FakeMongoMemoryStore)
    assert isinstance(bundle.graph_store, _FakeMongoGraphStore)
    assert bundle.memory_store._connection_string == "mongodb://localhost:27017/cellin"
    assert bundle.graph_store.shares_memory_store(bundle.memory_store)


def test_build_storage_bundle_rejects_mongodb_without_connection_string(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("mongodb"),
        graph=StorageBackendConfig("mongodb"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="mongodb backend requires a connection string"):
        build_storage_bundle(config, workspace_root=tmp_path)


def test_build_storage_bundle_resolves_redis_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_backend = object()

    class _FakeRedisMemoryStore(RedisMemoryStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    class _FakeRedisGraphStore(RedisGraphStore):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string
            self._backend = shared_backend

    monkeypatch.setattr("cellin.runtime.storage.RedisMemoryStore", _FakeRedisMemoryStore)
    monkeypatch.setattr("cellin.runtime.storage.RedisGraphStore", _FakeRedisGraphStore)
    config = StorageConfig(
        memory=StorageBackendConfig("redis", "redis://localhost:6379/0"),
        graph=StorageBackendConfig("redis", "redis://localhost:6379/0"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    bundle = build_storage_bundle(config, workspace_root=tmp_path)

    assert isinstance(bundle.memory_store, _FakeRedisMemoryStore)
    assert isinstance(bundle.graph_store, _FakeRedisGraphStore)
    assert bundle.memory_store._connection_string == "redis://localhost:6379/0"
    assert bundle.graph_store.shares_memory_store(bundle.memory_store)


def test_build_storage_bundle_rejects_redis_without_connection_string(tmp_path: Path) -> None:
    config = StorageConfig(
        memory=StorageBackendConfig("redis"),
        graph=StorageBackendConfig("redis"),
        vector=StorageBackendConfig("in_memory_vector_index"),
        representation=StorageBackendConfig("in_memory_vector_index"),
    )

    with pytest.raises(StorageBackendError, match="redis backend requires a connection string"):
        build_storage_bundle(config, workspace_root=tmp_path)


@pytest.mark.parametrize(
    "backend_name,graph_store_class",
    [
        ("neo4j", Neo4jGraphStore),
        ("memgraph", MemgraphGraphStore),
        ("arangodb", ArangoDBGraphStore),
    ],
)
def test_build_storage_bundle_resolves_graph_native_backends(
    backend_name: str,
    graph_store_class: type,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _FakeGraphStore(graph_store_class):
        def __init__(self, connection_string: str) -> None:
            self._connection_string = connection_string

    monkeypatch.setattr(
        f"cellin.runtime.storage.{graph_store_class.__name__}",
        _FakeGraphStore,
    )
    bundle = build_storage_bundle(
        StorageConfig(
            memory=StorageBackendConfig("in_memory"),
            graph=StorageBackendConfig(backend_name, f"{backend_name}://cellin/test"),
            vector=StorageBackendConfig("in_memory_vector_index"),
            representation=StorageBackendConfig("in_memory_vector_index"),
        ),
        workspace_root=tmp_path,
    )

    assert isinstance(bundle.graph_store, _FakeGraphStore)
    assert bundle.graph_store._connection_string == f"{backend_name}://cellin/test"


@pytest.mark.parametrize("backend_name", ["neo4j", "memgraph", "arangodb"])
def test_build_storage_bundle_rejects_graph_native_backends_without_connection_string(
    backend_name: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        StorageBackendError,
        match=f"{backend_name} backend requires a connection string",
    ):
        build_storage_bundle(
            StorageConfig(
                memory=StorageBackendConfig("in_memory"),
                graph=StorageBackendConfig(backend_name),
                vector=StorageBackendConfig("in_memory_vector_index"),
                representation=StorageBackendConfig("in_memory_vector_index"),
            ),
            workspace_root=tmp_path,
        )


def test_load_workspace_defaults_role_specific_graph_memory_path_when_missing(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "legacy-defaults.json"
    config_path.write_text(
        json.dumps({"storage": {"vector": {"backend": "in_memory_vector_index"}}}),
        encoding="utf-8",
    )
    workspace = load_workspace(config_path)

    assert workspace.storage == StorageConfig.with_in_memory_preset()


def test_load_workspace_defaults_to_in_memory_preset_when_storage_omitted(tmp_path: Path) -> None:
    config_path = tmp_path / "minimal.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")

    workspace = load_workspace(config_path)

    assert workspace.storage == StorageConfig.with_in_memory_preset()


def test_build_storage_bundle_resolves_sqlite_path_in_workspace(tmp_path: Path) -> None:
    bundle = build_storage_bundle(
        StorageConfig.with_sqlite_preset("subdir/cellin.sqlite"),
        workspace_root=tmp_path,
    )
    memory_store = bundle.memory_store
    assert isinstance(memory_store, SQLiteMemoryStore)
    assert memory_store._database_path == str((tmp_path / "subdir" / "cellin.sqlite").resolve())
