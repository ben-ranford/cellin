#!/usr/bin/env python3
"""Validate Cellin's release version surface."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from _versioning import (
    load_assigned_version,
    normalize_release_path,
    validate_release_kind,
)


def load_version(version_path: Path) -> str:
    return load_assigned_version(version_path.read_text(encoding="utf-8"))


def validate_pyproject(pyproject_path: Path, version_path: Path) -> None:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload["project"]
    dynamic = project.get("dynamic", [])
    if "version" not in dynamic:
        raise ValueError("pyproject.toml must declare project.dynamic = ['version']")

    configured_path = payload["tool"]["hatch"]["version"]["path"]
    normalized_configured = normalize_release_path(
        configured_path, relative_to=pyproject_path.parent
    )
    if normalized_configured != version_path:
        raise ValueError(
            f"tool.hatch.version.path must be {str(version_path)!r}, found {configured_path!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Cellin package version surface.")
    parser.add_argument("--tag", help="Git tag to compare against, for example v0.1.0")
    parser.add_argument("--expect-version", help="Expected package version")
    parser.add_argument(
        "--release-kind",
        choices=("any", "stable", "prerelease", "preview"),
        default="any",
        help="Validate stable, prerelease, or preview release policy",
    )
    parser.add_argument(
        "--version-path",
        default="src/cellin/__about__.py",
        help="Path to the version source file",
    )
    parser.add_argument(
        "--pyproject-path",
        default="pyproject.toml",
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="Print the resolved package version",
    )
    args = parser.parse_args()

    version_path = normalize_release_path(args.version_path)
    pyproject_path = normalize_release_path(args.pyproject_path)
    version = load_version(version_path)
    validate_pyproject(pyproject_path, version_path)
    if args.release_kind != "any":
        validate_release_kind(version, args.release_kind)

    if args.expect_version is not None and version != args.expect_version:
        raise ValueError(f"Expected package version {args.expect_version!r}, found {version!r}")

    if args.tag is not None:
        if not args.tag.startswith("v"):
            raise ValueError(f"Tags must be prefixed with 'v', found {args.tag!r}")
        if args.tag.removeprefix("v") != version:
            raise ValueError(f"Tag {args.tag!r} does not match package version {version!r}")

    if args.print_version:
        print(version)
    else:
        print(f"version={version} release_kind={args.release_kind}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
