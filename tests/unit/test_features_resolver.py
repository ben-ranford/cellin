"""Unit tests for feature resolution."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from cellin.features import FeatureFlag, load_release_lock, resolve_features
from cellin.features import resolver as resolver_module

TEST_REGISTRY = (
    FeatureFlag(
        code="preview_search",
        name="preview-search",
        description="Preview search",
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


def test_release_channel_defaults_to_stable_and_done() -> None:
    resolved = resolve_features(TEST_REGISTRY, "release", {}, (), ())

    assert resolved == {
        "preview_search": False,
        "stable_cache": True,
        "done_ingest": True,
    }


def test_dev_channel_matches_release_defaults() -> None:
    resolved = resolve_features(TEST_REGISTRY, "dev", {}, (), ())

    assert resolved == {
        "preview_search": False,
        "stable_cache": True,
        "done_ingest": True,
    }


def test_rolling_channel_enables_all_features_and_ignores_lock() -> None:
    resolved = resolve_features(
        TEST_REGISTRY,
        "rolling",
        {"preview_search": False},
        (),
        ("stable-cache",),
    )

    assert resolved == {
        "preview_search": True,
        "stable_cache": False,
        "done_ingest": True,
    }


def test_release_lock_defaults_preview_feature_on() -> None:
    resolved = resolve_features(TEST_REGISTRY, "release", {"preview_search": True}, (), ())

    assert resolved["preview_search"] is True


def test_explicit_opt_in_overrides_release_defaults() -> None:
    resolved = resolve_features(TEST_REGISTRY, "release", {}, ("preview-search",), ())

    assert resolved["preview_search"] is True


def test_explicit_opt_out_overrides_opt_in_and_release_lock() -> None:
    with pytest.raises(ValueError, match="both enabled and disabled"):
        resolve_features(
            TEST_REGISTRY,
            "release",
            {"preview_search": True},
            ("preview-search", "stable-cache"),
            ("preview-search", "stable-cache"),
        )


def test_explicit_opt_out_overrides_channel_defaults() -> None:
    resolved = resolve_features(
        TEST_REGISTRY,
        "release",
        {"preview_search": True},
        (),
        ("preview-search", "stable-cache"),
    )

    assert resolved == {
        "preview_search": False,
        "stable_cache": False,
        "done_ingest": True,
    }


def test_unknown_feature_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown feature names"):
        resolve_features(TEST_REGISTRY, "release", {}, ("unknown-feature",), ())


def test_conflicting_feature_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="both enabled and disabled"):
        resolve_features(TEST_REGISTRY, "release", {}, ("preview-search",), ("preview-search",))


def test_unknown_release_channel_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown release channel"):
        resolve_features(TEST_REGISTRY, "beta", {}, (), ())  # type: ignore[arg-type]


def test_unknown_release_lock_codes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown feature lock codes"):
        resolve_features(TEST_REGISTRY, "release", {"unknown_code": True}, (), ())


def test_release_lock_rejects_non_preview_features() -> None:
    with pytest.raises(ValueError, match="only enable preview features"):
        resolve_features(TEST_REGISTRY, "release", {"stable_cache": True}, (), ())


def test_load_release_lock_parses_and_validates_registry_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock_path = tmp_path / "features.release.lock.json"
    lock_path.write_text(json.dumps({"features": ["preview_search"]}), encoding="utf-8")
    monkeypatch.setattr(resolver_module, "REGISTRY", TEST_REGISTRY)

    assert load_release_lock(lock_path) == {"preview_search": True}


def test_load_release_lock_rejects_unknown_registry_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock_path = tmp_path / "features.release.lock.json"
    lock_path.write_text(json.dumps({"features": ["unknown_code"]}), encoding="utf-8")
    monkeypatch.setattr(resolver_module, "REGISTRY", TEST_REGISTRY)

    with pytest.raises(ValueError, match="Unknown feature lock codes"):
        load_release_lock(lock_path)


def test_load_release_lock_rejects_non_preview_registry_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock_path = tmp_path / "features.release.lock.json"
    lock_path.write_text(json.dumps({"features": ["stable_cache"]}), encoding="utf-8")
    monkeypatch.setattr(resolver_module, "REGISTRY", TEST_REGISTRY)

    with pytest.raises(ValueError, match="only enable preview features"):
        load_release_lock(lock_path)


@pytest.mark.parametrize(
    ("channel_env", "expected"),
    [
        (None, "release"),
        ("rolling", "rolling"),
    ],
)
def test_channel_metadata_uses_environment_override(
    monkeypatch: pytest.MonkeyPatch, channel_env: str | None, expected: str
) -> None:
    if channel_env is None:
        monkeypatch.delenv("CELLIN_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("CELLIN_RELEASE_CHANNEL", channel_env)

    module = importlib.import_module("cellin.__about__")
    module = importlib.reload(module)

    assert module.__channel__ == expected
