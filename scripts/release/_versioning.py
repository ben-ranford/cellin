"""Shared release versioning helpers for CI scripts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

VERSION_VALUE_PATTERN = r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.dev\d+)?"
VERSION_ASSIGNMENT_PATTERN = re.compile(
    rf'^(?P<prefix>__version__\s*=\s*")(?P<version>{VERSION_VALUE_PATTERN})(?P<suffix>"(?:\s*#.*)?)$',
    re.MULTILINE,
)
VERSION_BASE_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)")
STABLE_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
PRERELEASE_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:a|b|rc)\d+$")
PREVIEW_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.dev\d+$")
CONVENTIONAL_PATTERN = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]+\))?(?P<breaking>!)?:")

Bump = Literal["patch", "minor", "major"]
ReleaseKind = Literal["stable", "prerelease", "preview"]


@dataclass(frozen=True)
class CommitMessage:
    """Minimal commit message payload used for version inference."""

    subject: str
    body: str = ""


def load_assigned_version(text: str) -> str:
    """Extract the package version from a module source string."""

    match = VERSION_ASSIGNMENT_PATTERN.search(text)
    if match is None:
        raise ValueError("Unable to locate __version__ assignment")
    return match.group("version")


def replace_assigned_version(text: str, version: str) -> str:
    """Replace the package version while preserving inline comments."""

    validate_version(version)
    match = VERSION_ASSIGNMENT_PATTERN.search(text)
    if match is None:
        raise ValueError("Unable to locate __version__ assignment")
    return VERSION_ASSIGNMENT_PATTERN.sub(
        f"{match.group('prefix')}{version}{match.group('suffix')}",
        text,
        count=1,
    )


def validate_version(version: str) -> None:
    """Reject version strings that are outside the supported release model."""

    if not (
        STABLE_PATTERN.fullmatch(version)
        or PRERELEASE_PATTERN.fullmatch(version)
        or PREVIEW_PATTERN.fullmatch(version)
    ):
        raise ValueError("Versions must use X.Y.Z, X.Y.ZrcN/X.Y.ZbN/X.Y.ZaN, or X.Y.Z.devN")


def validate_release_kind(version: str, release_kind: ReleaseKind) -> None:
    """Validate a version against one of Cellin's release channels."""

    validate_version(version)
    if release_kind == "stable" and STABLE_PATTERN.fullmatch(version) is None:
        raise ValueError(f"Stable releases must use X.Y.Z, found {version!r}")
    if release_kind == "prerelease" and PRERELEASE_PATTERN.fullmatch(version) is None:
        raise ValueError(
            "Prereleases must use PEP 440 prerelease versions like X.Y.ZrcN, X.Y.ZbN, or X.Y.ZaN"
        )
    if release_kind == "preview" and PREVIEW_PATTERN.fullmatch(version) is None:
        raise ValueError("Preview releases must use PEP 440 development versions like X.Y.Z.devN")


def stable_base_version(version: str) -> str:
    """Return the stable base triple for any supported version string."""

    validate_version(version)
    match = VERSION_BASE_PATTERN.match(version)
    if match is None:
        raise ValueError(f"Unable to derive a stable base from {version!r}")
    return ".".join((match.group("major"), match.group("minor"), match.group("patch")))


def bump_stable_version(version: str, bump: Bump) -> str:
    """Increment a stable semver triple by the requested bump type."""

    if STABLE_PATTERN.fullmatch(version) is None:
        raise ValueError(f"Expected a stable version, found {version!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def infer_semver_bump(commits: Iterable[CommitMessage]) -> Bump:
    """Mirror the repo's release-please bump policy for preview builds."""

    highest: Bump = "patch"
    for commit in commits:
        subject = commit.subject.strip()
        body = commit.body
        match = CONVENTIONAL_PATTERN.match(subject)
        if "BREAKING CHANGE:" in body or (match is not None and match.group("breaking") == "!"):
            return "major"
        if match is not None and match.group("type") == "feat":
            highest = "minor"
    return highest


def derive_preview_base_version(stable_version: str, commits: Iterable[CommitMessage]) -> str:
    """Return the next preview base version after the latest stable cut."""

    return bump_stable_version(stable_version, infer_semver_bump(commits))


def build_preview_version(base_version: str, build_id: str) -> str:
    """Render a unique development release version."""

    if STABLE_PATTERN.fullmatch(base_version) is None:
        raise ValueError(f"Expected a stable preview base version, found {base_version!r}")
    if not build_id.isdigit():
        raise ValueError(f"Preview build ids must be numeric, found {build_id!r}")
    return f"{base_version}.dev{build_id}"
