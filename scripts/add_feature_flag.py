"""Allocate the next feature code and append it to the registry."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cellin.features.registry import FeatureFlag, validate_registry  # noqa: E402

FEATURE_CODE_PATTERN = re.compile(r"^CELN-FEAT-(\d{4})$")
DEFAULT_REGISTRY_PATH = REPO_ROOT / "src/cellin/features/registry.py"


@dataclass(frozen=True, slots=True)
class RegistryDefinition:
    """Parsed registry file details."""

    source: str
    tuple_start: int
    tuple_end: int
    features: tuple[FeatureFlag, ...]


def _position_to_offset(source: str, lineno: int, col_offset: int) -> int:
    line_offsets = [0]
    for line in source.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    return line_offsets[lineno - 1] + col_offset


def _feature_keyword_value(node: ast.Call, field_name: str) -> str:
    for keyword in node.keywords:
        if keyword.arg != field_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        break
    raise ValueError(f"FeatureFlag `{field_name}` must be a string literal.")


def _parse_feature_flag(node: ast.expr) -> FeatureFlag:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise ValueError("REGISTRY entries must be FeatureFlag(...) calls.")
    if node.func.id != "FeatureFlag":
        raise ValueError("REGISTRY entries must be FeatureFlag(...) calls.")

    return FeatureFlag(
        code=_feature_keyword_value(node, "code"),
        name=_feature_keyword_value(node, "name"),
        description=_feature_keyword_value(node, "description"),
        lifecycle=_feature_keyword_value(node, "lifecycle"),
    )


def load_registry_definition(path: Path = DEFAULT_REGISTRY_PATH) -> RegistryDefinition:
    """Parse the registry tuple from the registry module."""

    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)

    registry_value: ast.expr | None = None
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "REGISTRY"
            and node.value is not None
        ):
            registry_value = node.value
            break
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REGISTRY":
                    registry_value = node.value
                    break
            if registry_value is not None:
                break

    if registry_value is None:
        raise ValueError("REGISTRY assignment not found.")
    if not isinstance(registry_value, ast.Tuple):
        raise ValueError("REGISTRY must be defined as a tuple literal.")
    if registry_value.end_lineno is None or registry_value.end_col_offset is None:
        raise ValueError("REGISTRY tuple position metadata is unavailable.")

    features = tuple(_parse_feature_flag(node) for node in registry_value.elts)
    return RegistryDefinition(
        source=source,
        tuple_start=_position_to_offset(
            source,
            registry_value.lineno,
            registry_value.col_offset,
        ),
        tuple_end=_position_to_offset(
            source,
            registry_value.end_lineno,
            registry_value.end_col_offset,
        ),
        features=features,
    )


def next_feature_code(features: tuple[FeatureFlag, ...]) -> str:
    """Allocate the next CELN-FEAT code in sequence."""

    numbers = [
        int(match.group(1))
        for feature in features
        if (match := FEATURE_CODE_PATTERN.match(feature.code)) is not None
    ]
    return f"CELN-FEAT-{max(numbers, default=0) + 1:04d}"


def _default_description(name: str) -> str:
    return name.replace("-", " ")


def render_registry_tuple(features: tuple[FeatureFlag, ...]) -> str:
    """Render a canonical tuple literal for REGISTRY."""

    if not features:
        return "()"

    lines = ["("]
    for feature in features:
        lines.extend(
            (
                "    FeatureFlag(",
                f'        code="{feature.code}",',
                f'        name="{feature.name}",',
                f'        description="{feature.description}",',
                f'        lifecycle="{feature.lifecycle}",',
                "    ),",
            )
        )
    lines.append(")")
    return "\n".join(lines)


def add_feature_flag(name: str, registry_path: Path = DEFAULT_REGISTRY_PATH) -> FeatureFlag:
    """Append a preview feature flag entry to the registry file."""

    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Feature name must be non-empty.")

    registry = load_registry_definition(registry_path)
    validate_registry(registry.features)

    feature = FeatureFlag(
        code=next_feature_code(registry.features),
        name=normalized_name,
        description=_default_description(normalized_name),
        lifecycle="preview",
    )
    updated_features = registry.features + (feature,)
    validate_registry(updated_features)

    updated_source = (
        registry.source[: registry.tuple_start]
        + render_registry_tuple(updated_features)
        + registry.source[registry.tuple_end :]
    )
    registry_path.write_text(updated_source, encoding="utf-8")
    return feature


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        feature = add_feature_flag(args.name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(feature.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
