"""Shared store-layer utilities for memory filtering and common patterns."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from cellin.core import MemoryAtom


def filter_memories(
    memories: Iterable[MemoryAtom],
    *,
    archived: bool | None = None,
    topic: str | None = None,
) -> Sequence[MemoryAtom]:
    """Filter a flat sequence of memories by archived state and/or topic."""
    result: list[MemoryAtom] = []
    for memory in memories:
        if archived is not None and memory.decay.archived != archived:
            continue
        if topic is not None and memory.metadata.get("topic") != topic:
            continue
        result.append(memory)
    return result
