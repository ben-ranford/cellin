#!/usr/bin/env python3
"""Validate Cellin's release version surface."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

VERSION_PATTERN = re.compile(
    r'^__version__\s*=\s*"(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)"(?:\s*#.*)?\s*$',
    re.MULTILINE,
)
STABLE_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
PRERELEASE_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:a|b|rc)\d+$")


def load_version(version_path: Path) -> str:
    match = VERSION_PATTERN.search(version_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Unable to locate __version__ in {version_path}")
    return match.group("version")


def validate_pyproject(pyproject_path: Path, version_path: str) -> None:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload["project"]
    dynamic = project.get("dynamic", [])
    if "version" not in dynamic:
        raise ValueError("pyproject.toml must declare project.dynamic = ['version']")

    configured_path = payload["tool"]["hatch"]["version"]["path"]
    if configured_path != version_path:
        raise ValueError(
            f"tool.hatch.version.path must be {version_path!r}, found {configured_path!r}"
        )


def validate_release_kind(version: str, release_kind: str) -> None:
    if release_kind == "stable" and STABLE_PATTERN.fullmatch(version) is None:
        raise ValueError(f"Stable releases must use X.Y.Z, found {version!r}")
    if release_kind == "prerelease" and PRERELEASE_PATTERN.fullmatch(version) is None:
        raise ValueError(
            "Prereleases must use PEP 440 prerelease versions like X.Y.ZrcN, X.Y.ZbN, or X.Y.ZaN"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Cellin package version surface.")
    parser.add_argument("--tag", help="Git tag to compare against, for example v0.1.0")
    parser.add_argument("--expect-version", help="Expected package version")
    parser.add_argument(
        "--release-kind",
        choices=("any", "stable", "prerelease"),
        default="any",
        help="Validate stable or prerelease policy",
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

    version_path = Path(args.version_path)
    pyproject_path = Path(args.pyproject_path)
    version = load_version(version_path)
    validate_pyproject(pyproject_path, args.version_path)
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
