"""Feature flag registry primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

type Lifecycle = Literal["preview", "stable", "done"]

_VALID_LIFECYCLES: Final[frozenset[str]] = frozenset({"preview", "stable", "done"})


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    """Typed feature flag metadata."""

    code: str
    name: str
    description: str
    lifecycle: Lifecycle


REGISTRY: tuple[FeatureFlag, ...] = ()


def validate_registry(registry: tuple[FeatureFlag, ...] = REGISTRY) -> None:
    """Validate registry invariants."""

    seen_codes: set[str] = set()
    seen_active_names: set[str] = set()

    for feature in registry:
        if not feature.code:
            raise ValueError("Feature flags must define a non-empty code.")
        if feature.lifecycle not in _VALID_LIFECYCLES:
            raise ValueError(
                f"Feature `{feature.code}` has invalid lifecycle `{feature.lifecycle}`."
            )
        if feature.code in seen_codes:
            raise ValueError(f"Feature code `{feature.code}` is registered more than once.")
        seen_codes.add(feature.code)

        if feature.lifecycle == "done":
            continue

        if feature.name in seen_active_names:
            raise ValueError(f"Feature name `{feature.name}` is already used by an active feature.")
        seen_active_names.add(feature.name)
