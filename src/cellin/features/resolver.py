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


def parse_release_lock_document(
    raw: object,
    registry: tuple[FeatureFlag, ...] | None = None,
) -> ReleaseLockDocument:
    """Validate the raw release lock payload against the feature registry."""

    active_registry = REGISTRY if registry is None else registry
    validate_registry(active_registry)

    if not isinstance(raw, dict):
        raise ValueError("Release lock must be a JSON object.")

    unknown_keys = sorted(set(raw) - _RELEASE_LOCK_KEYS)
    if unknown_keys:
        raise ValueError(f"Release lock contains unknown keys: {', '.join(unknown_keys)}")

    missing_keys = sorted(_RELEASE_LOCK_KEYS - set(raw))
    if missing_keys:
        raise ValueError(f"Release lock is missing keys: {', '.join(missing_keys)}")

    release = raw["release"]
    if release is not None and not isinstance(release, str):
        raise ValueError("Release lock `release` must be a string or null.")

    default_on = raw["defaultOn"]
    if not isinstance(default_on, list):
        raise ValueError("Release lock must define a `defaultOn` list.")

    codes: list[str] = []
    for entry in default_on:
        if not isinstance(entry, str) or not entry:
            raise ValueError("Release lock feature codes must be non-empty strings.")
        codes.append(entry)

    if len(codes) != len(set(codes)):
        raise ValueError("Release lock contains duplicate feature codes.")

    notes_raw = raw["notes"]
    if not isinstance(notes_raw, dict):
        raise ValueError("Release lock `notes` must be a JSON object.")

    notes: dict[str, str] = {}
    for code, note in notes_raw.items():
        if not isinstance(code, str) or not code:
            raise ValueError("Release lock note keys must be non-empty strings.")
        if not isinstance(note, str):
            raise ValueError("Release lock note values must be strings.")
        notes[code] = note

    features_by_code = {feature.code: feature for feature in active_registry}
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
    return {code: True for code in document["defaultOn"]}
