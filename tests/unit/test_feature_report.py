"""Unit tests for the feature report generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cellin.features import FeatureFlag


def load_report_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_feature_report.py"
    spec = importlib.util.spec_from_file_location("generate_feature_report", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load feature report module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_module = load_report_module()

TEST_REGISTRY = (
    FeatureFlag(
        code="preview_search",
        name="preview-search",
        description="Preview search",
        lifecycle="preview",
    ),
    FeatureFlag(
        code="preview_index",
        name="preview-index",
        description="Preview index",
        lifecycle="preview",
    ),
    FeatureFlag(
        code="stable_cache",
        name="stable-cache",
        description="Stable cache",
        lifecycle="stable",
    ),
    FeatureFlag(
        code="done_ingest",
        name="done-ingest",
        description="Done ingest",
        lifecycle="done",
    ),
)


def test_build_feature_report_handles_empty_registry() -> None:
    report = report_module.build_feature_report(
        (),
        {"release": None, "defaultOn": [], "notes": {}},
        "release",
        (),
    )

    assert report == "\n".join(
        [
            "## Feature flags",
            "",
            "### Stable by default",
            "- None.",
            "",
            "### Preview available by opt-in",
            "- None.",
            "",
            "### Preview locked default-on for this release",
            "- None.",
            "",
            "### Newly added preview flags since previous release",
            "- None.",
        ]
    )


def test_build_feature_report_splits_mixed_feature_states() -> None:
    report = report_module.build_feature_report(
        TEST_REGISTRY,
        {
            "release": "v0.5.0",
            "defaultOn": ["preview_search"],
            "notes": {"preview_search": "Keep enabled while cache rollout settles."},
        },
        "release",
        (
            FeatureFlag(
                code="preview_search",
                name="preview-search",
                description="Preview search",
                lifecycle="preview",
            ),
        ),
    )

    assert "### Stable by default\n- `stable_cache` (`stable-cache`): Stable cache" in report
    assert "- `done_ingest` (`done-ingest`): Done ingest" in report
    assert (
        "### Preview available by opt-in\n- `preview_index` (`preview-index`): Preview index"
    ) in report
    assert (
        "### Preview locked default-on for this release\n"
        "- `preview_search` (`preview-search`): Preview search "
        "Note: Keep enabled while cache rollout settles."
    ) in report
    assert (
        "### Newly added preview flags since previous release\n"
        "- `preview_index` (`preview-index`): Preview index"
    ) in report


def test_build_feature_report_ignores_lock_for_rolling_channel() -> None:
    report = report_module.build_feature_report(
        TEST_REGISTRY,
        {
            "release": "v0.5.0",
            "defaultOn": ["preview_search"],
            "notes": {"preview_search": "Only for stable release artifacts."},
        },
        "rolling",
        (),
    )

    assert "### Preview locked default-on for this release\n- None." in report
    assert "- `preview_search` (`preview-search`): Preview search" in report


def test_load_registry_from_source_parses_literal_feature_flags() -> None:
    registry = report_module.load_registry_from_source(
        """
from cellin.features.registry import FeatureFlag

REGISTRY: tuple[FeatureFlag, ...] = (
    FeatureFlag(
        code="preview_search",
        name="preview-search",
        description="Preview search",
        lifecycle="preview",
    ),
)
"""
    )

    assert registry == (
        FeatureFlag(
            code="preview_search",
            name="preview-search",
            description="Preview search",
            lifecycle="preview",
        ),
    )


def test_load_registry_from_source_rejects_nonliteral_entries() -> None:
    source = """
from cellin.features.registry import FeatureFlag

description = "Preview search"
REGISTRY = (
    FeatureFlag(
        code="preview_search",
        name="preview-search",
        description=description,
        lifecycle="preview",
    ),
)
"""

    try:
        report_module.load_registry_from_source(source)
    except ValueError as exc:
        assert "description" in str(exc)
    else:
        raise AssertionError("Expected nonliteral registry source to fail.")
