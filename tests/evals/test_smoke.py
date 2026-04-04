"""Smoke eval tests used by local development and CI."""

from cellin.evals.smoke import run_smoke_eval


def test_smoke_eval_returns_ok_status() -> None:
    result = run_smoke_eval()

    assert result.system == "cellin"
    assert result.status == "ok"
    assert "eval-surface" in result.checks
