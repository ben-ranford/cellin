"""Tests that DeduplicationDreamStrategy emits DERIVED_FROM edges."""

from __future__ import annotations

from datetime import UTC, datetime

from cellin.core import (
    DecayState,
    EdgeKind,
    MemoryAtom,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.dreaming import DeduplicationDreamStrategy
from cellin.stores import InMemoryGraphStore as _InMemoryGraphStore
from cellin.stores import InMemoryMemoryStore as _InMemoryMemoryStore

_NOW = datetime(2026, 4, 22, tzinfo=UTC)


def _memory(memory_id: str, text: str, *, topic: str = "test-topic") -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id="test", source_type="fixture"),
        modality=Modality.TEXT,
        created_at=_NOW,
        observed_at=_NOW,
        metadata={"topic": topic},
        decay=DecayState(),
        retrieval=RetrievalStats(),
    )


def test_deduplication_emits_derived_from_edge_alongside_same_as() -> None:
    # Two near-identical memories sharing high Jaccard similarity
    mem_a = _memory("mem-a", "the atlas project stores memory atoms")
    mem_b = _memory("mem-b", "the atlas project stores memory atoms in graph")

    memory_store = _InMemoryMemoryStore((mem_a, mem_b))
    graph_store = _InMemoryGraphStore()

    strategy = DeduplicationDreamStrategy(similarity_threshold=0.5)
    result = strategy.execute(graph_store, memory_store, at=_NOW)

    assert result is not None, "Expected a DreamRunResult but got None"

    edges = graph_store.list_edges()
    kinds = {edge.kind for edge in edges}
    assert EdgeKind.SAME_AS in kinds, "SAME_AS edge not emitted"
    assert EdgeKind.DERIVED_FROM in kinds, "DERIVED_FROM edge not emitted"

    derived_edges = [e for e in edges if e.kind is EdgeKind.DERIVED_FROM]
    assert len(derived_edges) == 1
    derived = derived_edges[0]

    # The canonical (surviving) memory should be the source of DERIVED_FROM
    same_as_edges = [e for e in edges if e.kind is EdgeKind.SAME_AS]
    assert len(same_as_edges) == 1
    canonical_id = same_as_edges[0].target_id
    duplicate_id = same_as_edges[0].source_id

    assert derived.source_id == canonical_id
    assert derived.target_id == duplicate_id


def test_deduplication_derived_from_edge_change_is_recorded() -> None:
    mem_a = _memory("mem-x", "atlas deployment pipeline runs tests")
    mem_b = _memory("mem-y", "atlas deployment pipeline runs tests and checks")

    memory_store = _InMemoryMemoryStore((mem_a, mem_b))
    graph_store = _InMemoryGraphStore()

    strategy = DeduplicationDreamStrategy(similarity_threshold=0.5)
    result = strategy.execute(graph_store, memory_store, at=_NOW)

    assert result is not None
    diff = result.diff
    derived_from_changes = [
        ec
        for ec in diff.edge_changes
        if ec.after is not None and ec.after.kind is EdgeKind.DERIVED_FROM
    ]
    assert len(derived_from_changes) == 1


def test_no_derived_from_edge_when_no_merge_occurs() -> None:
    mem_a = _memory("mem-p", "atlas handles storage")
    mem_b = _memory("mem-q", "completely unrelated content about bananas")

    memory_store = _InMemoryMemoryStore((mem_a, mem_b))
    graph_store = _InMemoryGraphStore()

    strategy = DeduplicationDreamStrategy(similarity_threshold=0.92)
    strategy.execute(graph_store, memory_store, at=_NOW)

    # No merge should happen for dissimilar memories
    edges = graph_store.list_edges()
    assert not any(e.kind is EdgeKind.DERIVED_FROM for e in edges)
