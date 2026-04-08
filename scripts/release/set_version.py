#!/usr/bin/env python3
"""Rewrite Cellin's single-source version file."""

from __future__ import annotations

import argparse

from _versioning import normalize_release_path, replace_assigned_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the Cellin package version in-place.")
    parser.add_argument("--version", required=True, help="Target version string")
    parser.add_argument(
        "--version-path",
        default="src/cellin/__about__.py",
        help="Path to the version source file",
    )
    args = parser.parse_args()

    version_path = normalize_release_path(args.version_path)
    updated = replace_assigned_version(version_path.read_text(encoding="utf-8"), args.version)
    version_path.write_text(updated, encoding="utf-8")
    print(f"version={args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
