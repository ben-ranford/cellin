"""Integration coverage for storage discovery and setup CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import CaptureFixture

from cellin.cli import main
from cellin.cli.config import DEFAULT_CONFIG_FILENAME


def _workspace_config_path(workspace: Path) -> Path:
    return next(path for path in workspace.iterdir() if path.name == DEFAULT_CONFIG_FILENAME)


def _write_storage_config(config_path: Path, storage: dict[str, object]) -> Path:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["storage"] = storage
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    return config_path


def test_cli_storage_list_prints_builtin_backends(capsys: CaptureFixture[str]) -> None:
    assert main(["storage", "list", "--role", "memory"]) == 0

    output = capsys.readouterr().out
    assert "role=memory backend=in_memory" in output
    assert "role=memory backend=sqlite" in output


def test_cli_storage_init_dry_run_reports_default_in_memory_preset(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"

    assert main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    config_path = _workspace_config_path(workspace)

    assert main(["storage", "init", "--config", str(config_path), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "action=planned role=memory backend=in_memory" in output
    assert "action=planned role=graph backend=in_memory" in output
    assert "action=planned role=vector backend=in_memory_vector_index" in output
    assert (workspace / "cellin.sqlite").exists() is False


def test_cli_storage_init_initializes_sqlite_and_records_trace(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"

    assert main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    config_path = _workspace_config_path(workspace)
    _write_storage_config(
        config_path,
        {
            "memory": {"backend": "sqlite", "database_path": "cellin.sqlite"},
            "graph": {"backend": "sqlite", "database_path": "cellin.sqlite"},
            "vector": {"backend": "in_memory_vector_index"},
            "representation": {"backend": "in_memory_vector_index"},
        },
    )

    assert (
        main(
            [
                "storage",
                "init",
                "--config",
                str(config_path),
                "--role",
                "memory",
                "--role",
                "graph",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "action=initialized role=memory backend=sqlite" in output
    assert "action=initialized role=graph backend=sqlite" in output
    assert (workspace / "cellin.sqlite").exists()

    assert main(["trace", "inspect", "--config", str(config_path), "--limit", "1"]) == 0
    trace_output = capsys.readouterr().out
    assert "name=cli.storage.init" in trace_output
