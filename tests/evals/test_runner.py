"""Tests for the deterministic eval runner."""

from __future__ import annotations

import json
from pathlib import Path

from cellin.evals.runner import run_evaluation_suite


def test_smoke_suite_writes_report_with_deltas(tmp_path: Path) -> None:
    output_path = tmp_path / "smoke.json"

    report = run_evaluation_suite("smoke", output_path=output_path)

    assert report.status == "ok"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["suite"] == "smoke"
    assert payload["summary_metrics"]["case_count"] == 3.0
    assert payload["cases"][2]["case_id"] == "dream-atlas"
    assert "delta_metrics" in payload["cases"][2]


def test_full_suite_includes_performance_and_contradiction_cases(tmp_path: Path) -> None:
    output_path = tmp_path / "full.json"

    report = run_evaluation_suite("full", output_path=output_path)

    case_ids = tuple(case.case_id for case in report.cases)
    assert report.status == "ok"
    assert case_ids[-2:] == ("contradiction-repair", "performance-dedup")
    performance_case = report.cases[-1]
    assert performance_case.delta_metrics["active_memories"] < 0.0
    assert performance_case.delta_metrics["bundle_tokens"] < 0.0
