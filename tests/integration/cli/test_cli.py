"""Integration tests for the local CLI workflow."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import CaptureFixture

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
