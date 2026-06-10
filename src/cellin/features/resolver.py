"""Pure feature resolution helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final, Literal, TypedDict

from cellin.features.registry import REGISTRY, FeatureFlag, validate_registry

type ReleaseChannel = Literal["release", "dev", "rolling"]

_STABLE_LIFECYCLES: Final[frozenset[str]] = frozenset({"stable", "done"})
_RELEASE_LOCK_KEYS: Final[frozenset[str]] = frozenset({"release", "defaultOn", "notes"})


class ReleaseLockDocument(TypedDict):
    """Validated release lock payload."""

    release: str | None
    defaultOn: list[str]
    notes: dict[str, str]


def _feature_name_index(registry: tuple[FeatureFlag, ...]) -> dict[str, list[str]]:
    names_to_codes: dict[str, list[str]] = {}
    for feature in registry:
        names_to_codes.setdefault(feature.name, []).append(feature.code)
    return names_to_codes


def _validate_feature_name_overrides(
    names_to_codes: Mapping[str, list[str]],
    enabled_names: set[str],
    disabled_names: set[str],
) -> None:
    requested_names = enabled_names | disabled_names
    unknown_names = sorted(requested_names - set(names_to_codes))
    if unknown_names:
        raise ValueError(f"Unknown feature names: {', '.join(unknown_names)}")

    conflicts = sorted(enabled_names & disabled_names)
    if conflicts:
        raise ValueError(
            f"Feature names cannot be both enabled and disabled: {', '.join(conflicts)}"
        )

    ambiguous_names = sorted(name for name in requested_names if len(names_to_codes[name]) > 1)
    if ambiguous_names:
        raise ValueError(f"Feature names are ambiguous: {', '.join(ambiguous_names)}")


def _normalize_release_lock(
    lock: Mapping[str, bool] | None,
    features_by_code: Mapping[str, FeatureFlag],
) -> dict[str, bool]:
    normalized_lock = dict(lock or {})
    unknown_codes = sorted(set(normalized_lock) - set(features_by_code))
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
    return normalized_lock


def _default_feature_states(
    registry: tuple[FeatureFlag, ...],
    channel: ReleaseChannel,
) -> dict[str, bool]:
    if channel == "rolling":
        return {feature.code: True for feature in registry}
    if channel in {"release", "dev"}:
        return {feature.code: feature.lifecycle in _STABLE_LIFECYCLES for feature in registry}
    raise ValueError(f"Unknown release channel `{channel}`.")


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
    names_to_codes = _feature_name_index(registry)
    enabled_names = set(enable)
    disabled_names = set(disable)
    _validate_feature_name_overrides(names_to_codes, enabled_names, disabled_names)

    normalized_lock = _normalize_release_lock(lock, features_by_code)
    resolved = _default_feature_states(registry, channel)
    if channel != "rolling":
        for code, enabled in normalized_lock.items():
            if enabled:
                resolved[code] = True

    for name in enabled_names:
        resolved[names_to_codes[name][0]] = True

    for name in disabled_names:
        resolved[names_to_codes[name][0]] = False

    return resolved


def _release_lock_object(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError("Release lock must be a JSON object.")

    unknown_keys = sorted(set(raw) - _RELEASE_LOCK_KEYS)
    if unknown_keys:
        raise ValueError(f"Release lock contains unknown keys: {', '.join(unknown_keys)}")

    missing_keys = sorted(_RELEASE_LOCK_KEYS - set(raw))
    if missing_keys:
        raise ValueError(f"Release lock is missing keys: {', '.join(missing_keys)}")
    return raw


def _release_lock_codes(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("Release lock must define a `defaultOn` list.")

    codes: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            raise ValueError("Release lock feature codes must be non-empty strings.")
        codes.append(entry)

    if len(codes) != len(set(codes)):
        raise ValueError("Release lock contains duplicate feature codes.")
    return codes


def _release_lock_notes(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("Release lock `notes` must be a JSON object.")

    notes: dict[str, str] = {}
    for code, note in raw.items():
        if not isinstance(code, str) or not code:
            raise ValueError("Release lock note keys must be non-empty strings.")
        if not isinstance(note, str):
            raise ValueError("Release lock note values must be strings.")
        notes[code] = note
    return notes


def _validate_release_lock_feature_codes(
    codes: list[str],
    notes: Mapping[str, str],
    features_by_code: Mapping[str, FeatureFlag],
) -> None:
    unknown_codes = sorted(set(codes) - set(features_by_code))
    unknown_note_codes = sorted(set(notes) - set(features_by_code))
    unknown_codes.extend(code for code in unknown_note_codes if code not in unknown_codes)
    if unknown_codes:
        raise ValueError(f"Unknown feature lock codes: {', '.join(unknown_codes)}")

    non_preview_codes = sorted(
        code for code in codes if features_by_code[code].lifecycle != "preview"
    )
    if non_preview_codes:
        raise ValueError(
            f"Release lock can only enable preview features: {', '.join(non_preview_codes)}"
        )


def parse_release_lock_document(
    raw: object,
    registry: tuple[FeatureFlag, ...] | None = None,
) -> ReleaseLockDocument:
    """Validate the raw release lock payload against the feature registry."""

    active_registry = REGISTRY if registry is None else registry
    validate_registry(active_registry)
    release_lock = _release_lock_object(raw)

    release = release_lock["release"]
    if release is not None and not isinstance(release, str):
        raise ValueError("Release lock `release` must be a string or null.")

    codes = _release_lock_codes(release_lock["defaultOn"])
    notes = _release_lock_notes(release_lock["notes"])
    features_by_code = {feature.code: feature for feature in active_registry}
    _validate_release_lock_feature_codes(codes, notes, features_by_code)

    return {
        "release": release,
        "defaultOn": codes,
        "notes": notes,
    }


def read_release_lock_document(path: str | Path) -> ReleaseLockDocument:
    """Parse and validate a release lock file."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_release_lock_document(raw)


def load_release_lock(path: str | Path) -> dict[str, bool]:
    """Load the release lock as an effective code-to-enabled mapping."""

    document = read_release_lock_document(path)
    return dict.fromkeys(document["defaultOn"], True)
