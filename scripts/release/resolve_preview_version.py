#!/usr/bin/env python3
"""Resolve the next rolling preview version for the current Git ref."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _versioning import (
    CommitMessage,
    build_preview_version,
    derive_preview_base_version,
    load_assigned_version,
    select_latest_stable_tag,
    stable_base_version,
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _latest_stable_tag(ref: str) -> str | None:
    tags = _git("tag", "--merged", ref, "--sort=-v:refname")
    return select_latest_stable_tag(tags.splitlines())


def _commit_messages(revision_range: str) -> list[CommitMessage]:
    raw_log = _git("log", "--format=%s%x1f%b%x1e", revision_range)
    messages: list[CommitMessage] = []
    for record in raw_log.split("\x1e"):
        if not record.strip():
            continue
        subject, _, body = record.partition("\x1f")
        messages.append(CommitMessage(subject=subject.strip(), body=body.strip()))
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Cellin's rolling preview version.")
    parser.add_argument(
        "--run-id", required=True, help="GitHub run id or other numeric build identifier"
    )
    parser.add_argument(
        "--run-attempt", default="1", help="GitHub run attempt for rerun uniqueness"
    )
    parser.add_argument("--ref", default="HEAD", help="Git ref to resolve from")
    parser.add_argument(
        "--version-path",
        default="src/cellin/__about__.py",
        help="Path to the checked-in version source file",
    )
    args = parser.parse_args()

    build_id = f"{args.run_id}{int(args.run_attempt):02d}"
    stable_tag = _latest_stable_tag(args.ref)
    if stable_tag is None:
        current_version = load_assigned_version(Path(args.version_path).read_text(encoding="utf-8"))
        stable_version = stable_base_version(current_version)
        commits = _commit_messages(args.ref)
    else:
        stable_version = stable_tag.removeprefix("v")
        commits = _commit_messages(f"{stable_tag}..{args.ref}")

    preview_base = derive_preview_base_version(stable_version, commits)
    print(build_preview_version(preview_base, build_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
