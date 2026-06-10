#!/usr/bin/env python3
"""Generate a markdown feature flag report for release automation."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Final, cast

from cellin.features.registry import REGISTRY, FeatureFlag, Lifecycle, validate_registry
from cellin.features.resolver import ReleaseChannel, ReleaseLockDocument, read_release_lock_document

_STABLE_LIFECYCLES: Final[frozenset[str]] = frozenset({"stable", "done"})
_STABLE_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^v\d+\.\d+\.\d+$")


def format_feature(feature: FeatureFlag, note: str | None = None) -> str:
    """Format one feature row for markdown output."""

    line = f"- `{feature.code}` (`{feature.name}`): {feature.description}"
    if note:
        line = f"{line} Note: {note}"
    return line


def render_section(
    title: str,
    features: list[FeatureFlag],
    notes: dict[str, str] | None = None,
) -> list[str]:
    """Render a single feature report section."""

    lines = [f"### {title}"]
    if not features:
        lines.append("- None.")
        return lines

    section_notes = notes or {}
    for feature in features:
        lines.append(format_feature(feature, section_notes.get(feature.code)))
    return lines


def build_feature_report(
    registry: tuple[FeatureFlag, ...],
    lock: ReleaseLockDocument,
    channel: ReleaseChannel,
    previous_registry: tuple[FeatureFlag, ...],
) -> str:
    """Build the markdown feature report for the requested release channel."""

    validate_registry(registry)
    validate_registry(previous_registry)

    locked_codes = set(lock["defaultOn"]) if channel != "rolling" else set()
    previous_preview_codes = {
        feature.code for feature in previous_registry if feature.lifecycle == "preview"
    }

    stable_default = [feature for feature in registry if feature.lifecycle in _STABLE_LIFECYCLES]
    preview_opt_in = [
        feature
        for feature in registry
        if feature.lifecycle == "preview" and feature.code not in locked_codes
    ]
    preview_locked = [
        feature
        for feature in registry
        if feature.lifecycle == "preview" and feature.code in locked_codes
    ]
    new_preview = [
        feature
        for feature in registry
        if feature.lifecycle == "preview" and feature.code not in previous_preview_codes
    ]

    sections = [
        render_section("Stable by default", stable_default),
        render_section("Preview available by opt-in", preview_opt_in),
        render_section("Preview locked default-on for this release", preview_locked, lock["notes"]),
        render_section("Newly added preview flags since previous release", new_preview),
    ]

    lines = ["## Feature flags", ""]
    for index, section in enumerate(sections):
        if index:
            lines.append("")
        lines.extend(section)
    return "\n".join(lines)


def git_stdout(args: list[str], cwd: Path) -> str:
    """Run git and return decoded stdout."""

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def list_stable_tags(repo_root: Path) -> list[str]:
    """Return stable release tags sorted from newest to oldest."""

    try:
        tags = git_stdout(["tag", "--sort=-version:refname"], repo_root).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []

    return [tag for tag in tags if _STABLE_TAG_PATTERN.match(tag)]


def _find_registry_tuple(module: ast.Module) -> ast.Tuple:
    for node in module.body:
        value: ast.expr | None = None
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "REGISTRY"
        ):
            value = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REGISTRY":
                    value = node.value
                    break

        if value is None:
            continue
        if not isinstance(value, ast.Tuple):
            raise ValueError("Registry snapshot must define REGISTRY as a tuple literal.")
        return value

    raise ValueError("Registry snapshot must define REGISTRY.")


def _feature_keyword(node: ast.Call, field_name: str) -> str:
    for keyword in node.keywords:
        if keyword.arg != field_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        raise ValueError(f"Registry snapshot `{field_name}` values must be string literals.")
    raise ValueError(f"Registry snapshot entries must define `{field_name}`.")


def _parse_feature_entry(node: ast.expr) -> FeatureFlag:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise ValueError("Registry snapshot entries must be FeatureFlag(...) calls.")
    if node.func.id != "FeatureFlag":
        raise ValueError("Registry snapshot entries must be FeatureFlag(...) calls.")

    return FeatureFlag(
        code=_feature_keyword(node, "code"),
        name=_feature_keyword(node, "name"),
        description=_feature_keyword(node, "description"),
        lifecycle=cast(Lifecycle, _feature_keyword(node, "lifecycle")),
    )


def load_registry_from_source(source: str) -> tuple[FeatureFlag, ...]:
    """Parse a registry module source snapshot into feature metadata."""

    registry_tuple = _find_registry_tuple(ast.parse(source))
    normalized = tuple(_parse_feature_entry(entry) for entry in registry_tuple.elts)
    validate_registry(normalized)
    return normalized


def load_registry_from_ref(repo_root: Path, ref: str) -> tuple[FeatureFlag, ...]:
    """Load the feature registry from a git ref, or return an empty registry if unavailable."""

    try:
        source = git_stdout(["show", f"{ref}:src/cellin/features/registry.py"], repo_root)
    except (OSError, subprocess.CalledProcessError):
        return ()
    return load_registry_from_source(source)


def detect_previous_release_tag(repo_root: Path) -> str | None:
    """Find the previous stable release tag, skipping tags attached to HEAD."""

    tags = list_stable_tags(repo_root)
    if not tags:
        return None

    try:
        head_tags = set(git_stdout(["tag", "--points-at", "HEAD"], repo_root).splitlines())
    except (OSError, subprocess.CalledProcessError):
        head_tags = set()

    for tag in tags:
        if tag not in head_tags:
            return tag
    return None


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Generate a markdown feature flag report.")
    parser.add_argument(
        "--channel",
        choices=("release", "dev", "rolling"),
        required=True,
        help="Release channel to report for.",
    )
    parser.add_argument(
        "--lock",
        required=True,
        help="Path to features.release.lock.json.",
    )
    parser.add_argument(
        "--previous-ref",
        help="Optional git ref to compare preview flags against instead of auto-detecting.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""

    args = parse_args()
    lock_path = Path(args.lock)
    repo_root = Path.cwd()
    lock = read_release_lock_document(lock_path)

    previous_ref = args.previous_ref or detect_previous_release_tag(repo_root)
    previous_registry = load_registry_from_ref(repo_root, previous_ref) if previous_ref else ()

    print(build_feature_report(REGISTRY, lock, args.channel, previous_registry))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
