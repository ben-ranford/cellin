"""Unit coverage for CLI workspace storage config parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import cellin.cli.config as config_module
from cellin.cli.config import init_workspace, load_workspace
from cellin.features import FeatureFlag
from cellin.runtime.storage import StorageConfig

TEST_REGISTRY = (
    FeatureFlag(
        code="CELN-FEAT-0001",
        name="preview-search",
        description="Preview search",
        lifecycle="preview",
    ),
    FeatureFlag(
        code="CELN-FEAT-0002",
        name="stable-cache",
        description="Stable cache",
        lifecycle="stable",
    ),
)


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


def test_init_workspace_defaults_to_in_memory_preset(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = init_workspace(workspace)

    workspace_config = load_workspace(config_path)
    assert workspace_config.storage == StorageConfig.with_in_memory_preset()

    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["storage"] == {
        "memory": {"backend": "in_memory", "database_path": None},
        "graph": {"backend": "in_memory", "database_path": None},
        "vector": {"backend": "in_memory_vector_index", "database_path": None},
        "representation": {"backend": "in_memory_vector_index", "database_path": None},
    }

    assert "features" not in payload


def test_load_workspace_parses_features_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(
        tmp_path / "features.json",
        {"features": {"enable": ["preview-search"], "disable": ["stable-cache"]}},
    )

    workspace = load_workspace(config_path)

    assert workspace.features.enable == ("preview-search",)
    assert workspace.features.disable == ("stable-cache",)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"features": []}, "`features` must be an object"),
        ({"features": {"enable": "preview-search"}}, "`features.enable` must be a list"),
        ({"features": {"disable": [""]}}, "`features.disable` entries"),
        ({"features": {"enable": [7]}}, "`features.enable` entries"),
    ),
)
def test_load_workspace_rejects_invalid_features_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(tmp_path / "invalid-features.json", payload)

    with pytest.raises(ValueError, match=message):
        load_workspace(config_path)


def test_load_workspace_rejects_unknown_feature_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(
        tmp_path / "unknown-feature.json",
        {"features": {"enable": ["unknown-feature"]}},
    )

    with pytest.raises(ValueError, match="Unknown feature names: unknown-feature"):
        load_workspace(config_path)


def test_load_workspace_rejects_feature_activation_conflicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(
        tmp_path / "feature-conflict.json",
        {
            "features": {
                "enable": ["preview-search"],
                "disable": ["preview-search"],
            }
        },
    )

    with pytest.raises(ValueError, match="both enabled and disabled"):
        load_workspace(config_path)


def test_load_workspace_rejects_ambiguous_feature_activation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = (
        *TEST_REGISTRY,
        FeatureFlag(
            code="CELN-FEAT-0003",
            name="preview-search",
            description="Second preview search",
            lifecycle="done",
        ),
    )
    monkeypatch.setattr(config_module, "REGISTRY", registry)
    config_path = _write_config(
        tmp_path / "feature-ambiguous.json",
        {"features": {"enable": ["preview-search"]}},
    )

    with pytest.raises(ValueError, match="Feature names are ambiguous: preview-search"):
        load_workspace(config_path)


def test_load_workspace_rejects_unknown_features_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(
        tmp_path / "feature-keys.json",
        {"features": {"enable": [], "extra": []}},
    )

    with pytest.raises(ValueError, match="`features` contains unknown keys: extra"):
        load_workspace(config_path)


def test_sqlite_storage_role_uses_fallback_for_missing_and_empty_database_path() -> None:
    missing = config_module._coerce_storage_role(
        "memory",
        None,
        default_backend="sqlite",
        fallback_database_path="fallback.sqlite",
    )
    empty = config_module._coerce_storage_role(
        "graph",
        {"backend": "sqlite", "database_path": ""},
        default_backend="in_memory",
        fallback_database_path="fallback.sqlite",
    )

    assert missing.database_path == "fallback.sqlite"
    assert empty.database_path == "fallback.sqlite"
