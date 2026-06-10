"""Unit tests for feature registry validation."""

from __future__ import annotations

from typing import Any, cast

import pytest

from cellin.features import FeatureFlag, validate_registry


def test_validate_registry_accepts_empty_registry() -> None:
    validate_registry(())


def test_validate_registry_rejects_missing_code() -> None:
    registry = (
        FeatureFlag(
            code="",
            name="preview-search",
            description="Preview search",
            lifecycle="preview",
        ),
    )

    with pytest.raises(ValueError, match="non-empty code"):
        validate_registry(registry)


def test_validate_registry_rejects_duplicate_codes() -> None:
    registry = (
        FeatureFlag(
            code="preview_search",
            name="preview-search",
            description="Preview search",
            lifecycle="preview",
        ),
        FeatureFlag(
            code="preview_search",
            name="stable-search",
            description="Stable search",
            lifecycle="stable",
        ),
    )

    with pytest.raises(ValueError, match="registered more than once"):
        validate_registry(registry)


def test_validate_registry_rejects_duplicate_active_names() -> None:
    registry = (
        FeatureFlag(
            code="preview_search",
            name="shared-name",
            description="Preview search",
            lifecycle="preview",
        ),
        FeatureFlag(
            code="stable_search",
            name="shared-name",
            description="Stable search",
            lifecycle="stable",
        ),
    )

    with pytest.raises(ValueError, match="active feature"):
        validate_registry(registry)


def test_validate_registry_allows_duplicate_done_names() -> None:
    registry = (
        FeatureFlag(
            code="legacy_search_one",
            name="legacy-search",
            description="Legacy search rollout one",
            lifecycle="done",
        ),
        FeatureFlag(
            code="legacy_search_two",
            name="legacy-search",
            description="Legacy search rollout two",
            lifecycle="done",
        ),
    )

    validate_registry(registry)


def test_validate_registry_rejects_invalid_lifecycle() -> None:
    registry = (
        FeatureFlag(
            code="preview_search",
            name="preview-search",
            description="Preview search",
            lifecycle=cast(Any, "beta"),
        ),
    )

    with pytest.raises(ValueError, match="invalid lifecycle"):
        validate_registry(registry)
