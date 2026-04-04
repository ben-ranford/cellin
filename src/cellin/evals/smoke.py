"""Minimal smoke-eval utilities used by the bootstrap quality gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cellin.evals.runner import run_evaluation_suite


@dataclass(frozen=True)
class SmokeEvalResult:
    """A small deterministic result for the bootstrap smoke gate."""

    system: str
    status: str
    checks: tuple[str, ...]
    report_path: str


def run_smoke_eval(output_path: Path | None = None) -> SmokeEvalResult:
    """Return a deterministic bootstrap result for local and CI validation."""

    resolved_output = output_path or Path("eval-results/smoke.json")
    report = run_evaluation_suite("smoke", output_path=resolved_output)
    return SmokeEvalResult(
        system="cellin",
        status=report.status,
        checks=tuple(case.case_id for case in report.cases),
        report_path=str(resolved_output),
    )
