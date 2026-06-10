"""Pure feature resolution helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final, Literal

from cellin.features.registry import REGISTRY, FeatureFlag, validate_registry

type ReleaseChannel = Literal["release", "dev", "rolling"]

_STABLE_LIFECYCLES: Final[frozenset[str]] = frozenset({"stable", "done"})


def resolve_features(
    registry: tuple[FeatureFlag, ...],
    channel: ReleaseChannel,
    lock: Mapping[str, bool] | None,
    enable: Iterable[str],
    disable: Iterable[str],
) -> dict[str, bool]:
    """Resolve feature states for a release channel."""

    validate_registry(registry)

    features_by_code = {feature.code: feature for feature in registry}
    names_to_codes: dict[str, list[str]] = {}
    for feature in registry:
        names_to_codes.setdefault(feature.name, []).append(feature.code)

    enabled_names = set(enable)
    disabled_names = set(disable)
    known_names = set(names_to_codes)
    unknown_names = sorted((enabled_names | disabled_names) - known_names)
    if unknown_names:
        raise ValueError(f"Unknown feature names: {', '.join(unknown_names)}")

    conflicts = sorted(enabled_names & disabled_names)
    if conflicts:
        raise ValueError(
            f"Feature names cannot be both enabled and disabled: {', '.join(conflicts)}"
        )

    ambiguous_names = sorted(
        name for name in (enabled_names | disabled_names) if len(names_to_codes[name]) > 1
    )
    if ambiguous_names:
        raise ValueError(f"Feature names are ambiguous: {', '.join(ambiguous_names)}")

    normalized_lock = dict(lock or {})
    known_codes = set(features_by_code)
    unknown_codes = sorted(set(normalized_lock) - known_codes)
    if unknown_codes:
        raise ValueError(f"Unknown feature lock codes: {', '.join(unknown_codes)}")

    non_preview_codes = sorted(
        code
        for code, enabled in normalized_lock.items()
        if enabled and features_by_code[code].lifecycle != "preview"
    )
    if non_preview_codes:
        raise ValueError(
            f"Release lock can only enable preview features: {', '.join(non_preview_codes)}"
        )

    if channel == "rolling":
        resolved = {feature.code: True for feature in registry}
    elif channel in {"release", "dev"}:
        resolved = {feature.code: feature.lifecycle in _STABLE_LIFECYCLES for feature in registry}
    else:
        raise ValueError(f"Unknown release channel `{channel}`.")

    if channel != "rolling":
        for code, enabled in normalized_lock.items():
            if enabled:
                resolved[code] = True

    for name in enabled_names:
        resolved[names_to_codes[name][0]] = True

    for name in disabled_names:
        resolved[names_to_codes[name][0]] = False

    return resolved


def load_release_lock(path: str | Path) -> dict[str, bool]:
    """Parse and validate a release lock file."""

    validate_registry(REGISTRY)

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Release lock must be a JSON object.")

    features = raw.get("features")
    if not isinstance(features, list):
        raise ValueError("Release lock must define a `features` list.")

    codes: list[str] = []
    for entry in features:
        if not isinstance(entry, str) or not entry:
            raise ValueError("Release lock feature codes must be non-empty strings.")
        codes.append(entry)

    if len(codes) != len(set(codes)):
        raise ValueError("Release lock contains duplicate feature codes.")

    features_by_code = {feature.code: feature for feature in REGISTRY}
    unknown_codes = sorted(set(codes) - set(features_by_code))
    if unknown_codes:
        raise ValueError(f"Unknown feature lock codes: {', '.join(unknown_codes)}")

    non_preview_codes = sorted(
        code for code in codes if features_by_code[code].lifecycle != "preview"
    )
    if non_preview_codes:
        raise ValueError(
            f"Release lock can only enable preview features: {', '.join(non_preview_codes)}"
        )

    return {code: True for code in codes}
