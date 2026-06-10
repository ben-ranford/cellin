"""Unit tests for feature activation and registry helper scripts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

import cellin.cli.app as app_module
import cellin.cli.config as config_module
from cellin.features import FeatureFlag

TEST_REGISTRY = (
    FeatureFlag(
        code="CELN-FEAT-0001",
        name="preview-search",
        description="Preview search",
        lifecycle="preview",
    ),
    FeatureFlag(
        code="CELN-FEAT-0002",
        name="stable-cache",
        description="Stable cache",
        lifecycle="stable",
    ),
)


def _load_script_module(script_name: str) -> ModuleType:
    path = Path("scripts") / f"{script_name}.py"
    module_name = f"test_{script_name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_config(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_registry(path: Path, registry_body: str) -> Path:
    path.write_text(dedent(registry_body), encoding="utf-8")
    return path


def test_add_feature_flag_allocates_next_code_and_appends_preview_entry(tmp_path: Path) -> None:
    add_feature_flag_module = _load_script_module("add_feature_flag")
    registry_path = _write_registry(
        tmp_path / "registry.py",
        """
        from __future__ import annotations

        from cellin.features.registry import FeatureFlag

        REGISTRY: tuple[FeatureFlag, ...] = (
            FeatureFlag(
                code="CELN-FEAT-0007",
                name="stable-cache",
                description="Stable cache",
                lifecycle="stable",
            ),
        )
        """,
    )

    feature = add_feature_flag_module.add_feature_flag("preview-search", registry_path)
    definition = add_feature_flag_module.load_registry_definition(registry_path)

    assert feature.code == "CELN-FEAT-0008"
    assert feature.name == "preview-search"
    assert feature.description == "preview search"
    assert feature.lifecycle == "preview"
    assert definition.features[-1] == feature


def test_add_feature_flag_rejects_duplicate_registry_state(tmp_path: Path) -> None:
    add_feature_flag_module = _load_script_module("add_feature_flag")
    registry_path = _write_registry(
        tmp_path / "registry.py",
        """
        from __future__ import annotations

        from cellin.features.registry import FeatureFlag

        REGISTRY: tuple[FeatureFlag, ...] = (
            FeatureFlag(
                code="CELN-FEAT-0001",
                name="preview-search",
                description="Preview search",
                lifecycle="preview",
            ),
            FeatureFlag(
                code="CELN-FEAT-0001",
                name="stable-cache",
                description="Stable cache",
                lifecycle="stable",
            ),
        )
        """,
    )

    with pytest.raises(ValueError, match="registered more than once"):
        add_feature_flag_module.add_feature_flag("next-feature", registry_path)


def test_check_feature_registry_returns_zero_for_valid_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_feature_registry_module = _load_script_module("check_feature_registry")
    monkeypatch.setattr(check_feature_registry_module, "REGISTRY", TEST_REGISTRY)

    assert check_feature_registry_module.main() == 0


def test_check_feature_registry_returns_nonzero_for_invalid_registry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check_feature_registry_module = _load_script_module("check_feature_registry")
    monkeypatch.setattr(
        check_feature_registry_module,
        "REGISTRY",
        (
            FeatureFlag(
                code="CELN-FEAT-0001",
                name="preview-search",
                description="Preview search",
                lifecycle="preview",
            ),
            FeatureFlag(
                code="CELN-FEAT-0001",
                name="stable-cache",
                description="Stable cache",
                lifecycle="stable",
            ),
        ),
    )

    assert check_feature_registry_module.main() == 1
    assert "registered more than once" in capsys.readouterr().err


def test_resolve_feature_context_merges_cli_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(app_module, "REGISTRY", TEST_REGISTRY)
    monkeypatch.setattr(config_module, "REGISTRY", TEST_REGISTRY)
    config_path = _write_config(
        tmp_path / "cellin.json",
        {"features": {"enable": ["stable-cache"], "disable": ["preview-search"]}},
    )

    args = app_module.build_parser().parse_args(
        [
            "--enable-feature",
            "preview-search",
            "--disable-feature",
            "stable-cache",
            "retrieve",
            "--config",
            str(config_path),
            "--query",
            "hello",
        ]
    )
    context = app_module._resolve_feature_context(args)

    assert context.enabled_names == ("preview-search",)
    assert context.disabled_names == ("stable-cache",)
    assert context.resolved == {
        "CELN-FEAT-0001": True,
        "CELN-FEAT-0002": False,
    }


def test_resolve_feature_context_rejects_unknown_cli_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "REGISTRY", TEST_REGISTRY)
    args = app_module.build_parser().parse_args(
        ["--enable-feature", "unknown-feature", "plugin", "list"]
    )

    with pytest.raises(ValueError, match="Unknown feature names: unknown-feature"):
        app_module._resolve_feature_context(args)
