"""Minimal smoke-eval utilities used by the bootstrap quality gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SmokeEvalResult:
    """A small deterministic result for the bootstrap smoke gate."""

    system: str
    status: str
    checks: tuple[str, ...]


def run_smoke_eval() -> SmokeEvalResult:
    """Return a deterministic bootstrap result for local and CI validation."""

    return SmokeEvalResult(
        system="cellin",
        status="ok",
        checks=("package-import", "eval-surface"),
    )
