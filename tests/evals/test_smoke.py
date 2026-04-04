"""Smoke eval tests used by local development and CI."""

from pathlib import Path

from cellin.evals.smoke import run_smoke_eval


def test_smoke_eval_returns_ok_status(tmp_path: Path) -> None:
    result = run_smoke_eval(tmp_path / "smoke.json")

    assert result.system == "cellin"
    assert result.status == "ok"
    assert "ingest-multimodal" in result.checks
