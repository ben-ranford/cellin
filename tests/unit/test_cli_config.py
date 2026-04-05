"""Unit coverage for CLI workspace storage config parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cellin.cli.config import load_workspace


def _write_config(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_workspace_rejects_non_object_json(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "invalid.json", ["not", "an", "object"])

    with pytest.raises(ValueError, match="JSON object"):
        load_workspace(config_path)


def test_load_workspace_rejects_non_object_storage(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "invalid-storage.json", {"storage": []})

    with pytest.raises(ValueError, match="`storage` must be an object"):
        load_workspace(config_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"storage": {"memory": []}}, "`memory` storage config must be an object"),
        (
            {"storage": {"graph": {"backend": 3}}},
            "`graph` storage backend must be a string",
        ),
        (
            {"storage": {"memory": {"backend": "sqlite", "database_path": 7}}},
            "`memory` storage database_path must be a string",
        ),
    ),
)
def test_load_workspace_rejects_invalid_role_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    config_path = _write_config(tmp_path / "invalid-role.json", payload)

    with pytest.raises(ValueError, match=message):
        load_workspace(config_path)


def test_load_workspace_treats_empty_sqlite_database_path_as_legacy_fallback(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path / "fallback.json",
        {
            "database_path": "legacy.sqlite",
            "storage": {
                "memory": {"backend": "sqlite", "database_path": ""},
                "graph": {"backend": "sqlite"},
            },
        },
    )

    workspace = load_workspace(config_path)

    assert workspace.storage.memory.database_path == "legacy.sqlite"
    assert workspace.storage.graph.database_path == "legacy.sqlite"
