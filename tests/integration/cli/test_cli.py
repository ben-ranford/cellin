"""Integration tests for the local CLI workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import CaptureFixture

from cellin import __version__
from cellin.cli import main


def _copy_example_input(target: Path) -> Path:
    source = Path("examples/starter/seed_envelopes.json")
    destination = target / "seed_envelopes.json"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def test_cli_end_to_end_flow(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / "cellin.json"
    input_path = _copy_example_input(tmp_path)
    eval_output = tmp_path / "smoke.json"

    assert main(["init", "--workspace", str(workspace)]) == 0
    init_output = capsys.readouterr().out
    assert "initialized workspace" in init_output

    assert main(["ingest", "--config", str(config_path), "--input", str(input_path)]) == 0
    ingest_output = capsys.readouterr().out
    assert "memories=4" in ingest_output

    assert (
        main(
            [
                "retrieve",
                "--config",
                str(config_path),
                "--query",
                "memory graph retrieval",
                "--top-k",
                "2",
            ]
        )
        == 0
    )
    retrieve_output = capsys.readouterr().out
    assert "memory_id=" in retrieve_output
    assert "factors=[" in retrieve_output

    assert main(["dream", "--config", str(config_path), "--strategy", "abstraction"]) == 0
    dream_output = capsys.readouterr().out
    assert "strategy=abstraction" in dream_output

    assert main(["plugin", "list"]) == 0
    plugin_output = capsys.readouterr().out
    assert "plugin_id=in-memory-trace-sink" in plugin_output

    assert (
        main(
            [
                "eval",
                "run",
                "--suite",
                "smoke",
                "--config",
                str(config_path),
                "--output",
                str(eval_output),
            ]
        )
        == 0
    )
    eval_output_text = capsys.readouterr().out
    assert "suite=smoke status=ok" in eval_output_text
    payload = json.loads(eval_output.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"

    assert main(["trace", "inspect", "--config", str(config_path), "--limit", "5"]) == 0
    trace_output = capsys.readouterr().out
    assert "name=cli.ingest" in trace_output
    assert "name=cli.eval" in trace_output


def test_cli_version_flag(capsys: CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    version_output = capsys.readouterr().out.strip()
    assert version_output.endswith(__version__)


def test_trace_inspect_zero_and_negative_limits_emit_no_entries(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / "cellin.json"
    input_path = _copy_example_input(tmp_path)

    assert main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    assert main(["ingest", "--config", str(config_path), "--input", str(input_path)]) == 0
    capsys.readouterr()

    assert main(["trace", "inspect", "--config", str(config_path), "--limit", "0"]) == 0
    zero_limit_output = capsys.readouterr().out
    assert zero_limit_output.strip() == "no trace events recorded"

    assert main(["trace", "inspect", "--config", str(config_path), "--limit", "-1"]) == 0
    negative_limit_output = capsys.readouterr().out
    assert negative_limit_output.strip() == "no trace events recorded"
