"""Unit tests for release version derivation helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "release" / "_versioning.py"
    spec = importlib.util.spec_from_file_location("cellin_release_versioning", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load release versioning helpers")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_versioning = _load_module()
CommitMessage = release_versioning.CommitMessage


def test_replace_assigned_version_preserves_inline_comment() -> None:
    source = '__version__ = "0.2.0"  # x-release-please-version\n'

    updated = release_versioning.replace_assigned_version(source, "0.2.1.dev42")

    assert updated == '__version__ = "0.2.1.dev42"  # x-release-please-version\n'


@pytest.mark.parametrize(
    ("commits", "expected"),
    (
        ([CommitMessage(subject="fix(retrieval): enforce token budget")], "0.2.1"),
        ([CommitMessage(subject="feat(runtime): add preview lane")], "0.3.0"),
        (
            [
                CommitMessage(subject="fix(retrieval): enforce token budget"),
                CommitMessage(subject="feat(runtime): add preview lane"),
            ],
            "0.3.0",
        ),
        ([CommitMessage(subject="feat(runtime)!: break plugin API")], "1.0.0"),
        ([CommitMessage(subject="docs(readme): refresh install docs")], "0.2.1"),
    ),
)
def test_derive_preview_base_version_matches_repo_bump_policy(
    commits: list[object], expected: str
) -> None:
    assert release_versioning.derive_preview_base_version("0.2.0", commits) == expected


def test_infer_semver_bump_recognizes_breaking_change_in_body() -> None:
    commit = CommitMessage(
        subject="refactor(runtime): simplify plugin API",
        body="BREAKING CHANGE: plugin constructors now require settings",
    )

    assert release_versioning.infer_semver_bump([commit]) == "major"


def test_build_preview_version_uses_numeric_build_identifier() -> None:
    assert release_versioning.build_preview_version("0.2.1", "1234501") == "0.2.1.dev1234501"


def test_build_preview_version_rejects_non_numeric_build_identifier() -> None:
    with pytest.raises(ValueError, match="numeric"):
        release_versioning.build_preview_version("0.2.1", "run-42")


def test_select_latest_stable_tag_ignores_preview_and_candidate_tags() -> None:
    tags = ["v0.2.1.dev2399631184001", "v0.2.1rc1", "v0.2.0", "v0.1.1"]

    assert release_versioning.select_latest_stable_tag(tags) == "v0.2.0"


def test_normalize_release_path_uses_repository_root_by_default() -> None:
    normalized = release_versioning.normalize_release_path("src/cellin/__about__.py")

    assert normalized == (release_versioning.REPO_ROOT / "src" / "cellin" / "__about__.py")


def test_normalize_release_path_uses_custom_base_for_relative_inputs() -> None:
    base = Path("test-path-root")
    expected = (base / "pyproject.toml").resolve()

    assert release_versioning.normalize_release_path("pyproject.toml", relative_to=base) == expected


def test_normalize_release_path_ignores_base_for_absolute_paths(
    tmp_path: Path,
) -> None:
    absolute = (tmp_path / "cellin-test-about.py").resolve()

    assert release_versioning.normalize_release_path(str(absolute)) == absolute
