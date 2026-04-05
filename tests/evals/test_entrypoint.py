"""Coverage for the eval suite command-line entrypoint."""

from __future__ import annotations

import runpy
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest import CaptureFixture

from cellin.evals.__main__ import main
from cellin.evals.runner import EvaluationCaseResult, EvaluationReport


def _report(status: str) -> EvaluationReport:
    return EvaluationReport(
        suite="smoke",
        status=status,
        generated_at=datetime(2026, 4, 5, tzinfo=UTC),
        cases=(EvaluationCaseResult(case_id="smoke-case", status=status, metrics={}),),
        summary_metrics={},
    )


def test_eval_main_uses_default_output_path_and_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run_evaluation_suite(
        suite: str, *, output_path: Path | None = None
    ) -> EvaluationReport:
        captured["suite"] = suite
        captured["output_path"] = output_path
        return _report("failed")

    monkeypatch.setattr("cellin.evals.__main__.run_evaluation_suite", fake_run_evaluation_suite)
    monkeypatch.setattr(sys, "argv", ["cellin.evals", "full"])

    assert main() == 1
    assert captured == {"suite": "full", "output_path": Path("eval-results") / "full.json"}
    assert capsys.readouterr().out.strip() == "smoke: failed -> eval-results/full.json"


def test_eval_module_entrypoint_exits_with_status_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_evaluation_suite(_: str, *, output_path: Path | None = None) -> EvaluationReport:
        assert output_path == Path("eval-results") / "smoke.json"
        return _report("ok")

    monkeypatch.setattr("cellin.evals.runner.run_evaluation_suite", fake_run_evaluation_suite)
    monkeypatch.setattr(sys, "argv", ["cellin.evals", "smoke"])
    sys.modules.pop("cellin.evals.__main__", None)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("cellin.evals.__main__", run_name="__main__")

    assert excinfo.value.code == 0
