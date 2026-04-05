"""Additional CLI coverage for entrypoints and no-op paths."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from pytest import CaptureFixture

from cellin.cli import main
from cellin.cli.config import DEFAULT_CONFIG_FILENAME


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

    assert main(["dream", "--config", str(config_path)]) == 0
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
