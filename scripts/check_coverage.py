"""Fail when overall or per-package line coverage drops below configured thresholds."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _package_name(path: Path, source_root: Path) -> str:
    relative_path = path.relative_to(source_root)
    return source_root.name if len(relative_path.parts) == 1 else relative_path.parts[0]


def _load_package_totals(
    raw: dict[str, object],
    *,
    source_root: Path,
) -> dict[str, tuple[int, int]]:
    files = raw["files"]
    assert isinstance(files, dict)
    package_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    source_root = source_root.resolve()

    for path_str, data in files.items():
        path = Path(path_str).resolve()
        if not path.is_relative_to(source_root):
            continue
        assert isinstance(data, dict)
        summary = data["summary"]
        assert isinstance(summary, dict)
        covered = int(summary["covered_lines"])
        statements = int(summary["num_statements"])
        package_name = _package_name(path, source_root)
        package_totals[package_name][0] += covered
        package_totals[package_name][1] += statements

    return {name: (totals[0], totals[1]) for name, totals in package_totals.items()}


def _percent(covered: int, statements: int) -> float:
    return 100.0 if statements == 0 else 100.0 * covered / statements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--overall", type=float, required=True)
    parser.add_argument("--package", type=float, required=True)
    args = parser.parse_args()

    raw = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    totals = raw["totals"]
    assert isinstance(totals, dict)

    total_covered = int(totals["covered_lines"])
    total_statements = int(totals["num_statements"])
    overall_percent = _percent(total_covered, total_statements)
    package_totals = _load_package_totals(raw, source_root=args.source_root)

    print(
        "Overall coverage: "
        f"{overall_percent:.2f}% ({total_covered}/{total_statements}) "
        f"[minimum {args.overall:.2f}%]"
    )
    print("Per-package coverage:")
    for package_name, (covered, statements) in sorted(package_totals.items()):
        print(
            f"- {package_name}: {_percent(covered, statements):.2f}% "
            f"({covered}/{statements}) [minimum {args.package:.2f}%]"
        )

    failures: list[str] = []
    if overall_percent < args.overall:
        failures.append(
            f"overall coverage {overall_percent:.2f}% is below minimum {args.overall:.2f}%"
        )

    for package_name, (covered, statements) in sorted(package_totals.items()):
        package_percent = _percent(covered, statements)
        if package_percent < args.package:
            failures.append(
                f"package {package_name} coverage {package_percent:.2f}% "
                f"is below minimum {args.package:.2f}%"
            )

    if not failures:
        print("Coverage thresholds satisfied.")
        return 0

    print("Coverage threshold failures:")
    for failure in failures:
        print(f"- {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
