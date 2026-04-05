"""Tests for workspace storage configuration migration and backend resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cellin.cli.config import DEFAULT_DATABASE_FILENAME, load_workspace
from cellin.runtime.storage import (
    StorageBackendConfig,
    StorageBackendError,
    StorageConfig,
    build_storage_bundle,
)
from cellin.stores import SQLiteMemoryStore


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


def test_load_workspace_defaults_role_specific_graph_memory_path_when_missing(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "legacy-defaults.json"
    config_path.write_text(
        json.dumps({"storage": {"vector": {"backend": "in_memory_vector_index"}}}),
        encoding="utf-8",
    )
    workspace = load_workspace(config_path)

    assert workspace.storage == StorageConfig.with_sqlite_preset(DEFAULT_DATABASE_FILENAME)
    assert workspace.storage.vector.backend == "in_memory_vector_index"


def test_build_storage_bundle_resolves_sqlite_path_in_workspace(tmp_path: Path) -> None:
    bundle = build_storage_bundle(
        StorageConfig.with_sqlite_preset("subdir/cellin.sqlite"),
        workspace_root=tmp_path,
    )
    memory_store = bundle.memory_store
    assert isinstance(memory_store, SQLiteMemoryStore)
    assert memory_store._database_path == str((tmp_path / "subdir" / "cellin.sqlite").resolve())
