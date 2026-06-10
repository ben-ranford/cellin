"""Additional CLI coverage for entrypoints and no-op paths."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from pytest import CaptureFixture

import cellin.cli.app as app_module
from cellin.cli import main
from cellin.cli.config import DEFAULT_CONFIG_FILENAME
from cellin.features import FeatureFlag

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


def test_cli_module_entrypoint_uses_app_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_main() -> int:
        nonlocal called
        called = True
        return 7

    monkeypatch.setattr("cellin.cli.app.main", fake_main)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("cellin.cli.__main__", run_name="__main__")

    assert called is True
    assert excinfo.value.code == 7


def test_cli_handles_no_pending_dreams_and_missing_trace_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / DEFAULT_CONFIG_FILENAME

    assert main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()

    assert main(["dream", "run", "--config", str(config_path)]) == 0
    assert capsys.readouterr().out.strip() == "no dream runs executed"

    assert main(["trace", "inspect", "--config", str(config_path), "--limit", "1"]) == 0
    assert capsys.readouterr().out.strip() == "no trace events recorded"


def test_cli_plugin_list_ignores_entry_point_load_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def raise_value_error(self) -> tuple[str, ...]:
        raise ValueError("bad plugin")

    monkeypatch.setattr("cellin.cli.app.PluginRegistry.load_entry_points", raise_value_error)

    assert main(["plugin", "list"]) == 0

    output = capsys.readouterr().out
    assert "plugin_id=in-memory-trace-sink" in output


def test_cli_features_list_emits_table_and_json(
    monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_module, "REGISTRY", TEST_REGISTRY)
    monkeypatch.setenv("CELLIN_RELEASE_CHANNEL", "release")

    assert main(["features", "list"]) == 0
    table_output = capsys.readouterr().out.splitlines()
    assert table_output[0].split() == ["CODE", "NAME", "LIFECYCLE", "DEFAULT"]
    assert any("CELN-FEAT-0001" in line and "disabled" in line for line in table_output[1:])
    assert any("CELN-FEAT-0002" in line and "enabled" in line for line in table_output[1:])

    assert main(["features", "list", "--format", "json"]) == 0
    json_output = json.loads(capsys.readouterr().out)
    assert json_output == [
        {
            "code": "CELN-FEAT-0001",
            "default_enabled": False,
            "lifecycle": "preview",
            "name": "preview-search",
        },
        {
            "code": "CELN-FEAT-0002",
            "default_enabled": True,
            "lifecycle": "stable",
            "name": "stable-cache",
        },
    ]


def test_cli_rejects_unknown_global_feature_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "REGISTRY", TEST_REGISTRY)

    with pytest.raises(ValueError, match="Unknown feature names: unknown-feature"):
        main(["--enable-feature", "unknown-feature", "plugin", "list"])


def test_feature_context_reports_missing_codes_disabled() -> None:
    context = app_module.FeatureContext(
        channel="release",
        enabled_names=(),
        disabled_names=(),
        resolved={"CELN-FEAT-0001": True},
    )

    assert context.is_enabled("CELN-FEAT-0001") is True
    assert context.is_enabled("CELN-FEAT-9999") is False


def test_cli_rejects_unknown_release_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELLIN_RELEASE_CHANNEL", "beta")

    with pytest.raises(ValueError, match="Unknown release channel"):
        main(["plugin", "list"])


def test_cli_storage_list_ignores_backend_entry_point_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def raise_type_error() -> None:
        raise TypeError("bad entry point")

    monkeypatch.setattr(app_module, "load_storage_backends_from_entry_points", raise_type_error)

    assert main(["storage", "list"]) == 0
    output = capsys.readouterr().out

    assert "role=memory backend=in_memory" in output


def test_cli_storage_init_reports_empty_selection(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / DEFAULT_CONFIG_FILENAME

    assert main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "storage",
                "init",
                "--config",
                str(config_path),
                "--backend",
                "missing",
                "--dry-run",
            ]
        )
        == 0
    )

    assert "no storage backends selected" in capsys.readouterr().out


def test_eval_storage_config_unknown_backend_falls_back_to_default() -> None:
    assert app_module._resolve_eval_storage_config("custom") is None


def test_cli_mcp_serve_check_reports_startup_status(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "mcp",
                "serve",
                "--workspace-root",
                str(tmp_path),
                "--data-dir",
                "subjects",
                "--check",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["workspace_root"] == str(tmp_path.resolve())
    assert payload["data_directory"] == str((tmp_path / "subjects").resolve())


def test_cli_mcp_serve_check_uses_env_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "env-data"
    monkeypatch.setenv("CELLIN_BACKEND", "in_memory")
    monkeypatch.setenv("CELLIN_DATA_DIR", str(data_dir))

    assert main(["mcp", "serve", "--workspace-root", str(tmp_path), "--check"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["data_directory"] == str(data_dir.resolve())
