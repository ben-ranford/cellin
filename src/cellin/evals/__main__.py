"""Command-line entry point for deterministic eval suites."""

from __future__ import annotations

import argparse
from pathlib import Path

from cellin.evals.runner import run_evaluation_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Cellin eval suites.")
    parser.add_argument("suite", choices=("smoke", "full"))
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to the JSON report to write.",
    )
    args = parser.parse_args()
    output_path = args.output or Path("eval-results") / f"{args.suite}.json"
    report = run_evaluation_suite(args.suite, output_path=output_path)
    print(f"{report.suite}: {report.status} -> {output_path}")
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
