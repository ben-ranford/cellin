"""Unit tests for issues #160, #161, and #168."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cellin.core import (
    Capability,
    DecayState,
    MemoryAtom,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
    VectorMatch,
)
from cellin.ranking.profiles import WeightProfile, get_weight_profile
from cellin.ranking.weighted import WeightedRanker
from cellin.retrieval.candidate_generation import RetrievalCandidateGenerator
from cellin.retrieval.service import WeightedRetriever
from cellin.runtime import PluginRegistry, WeightedRankerPlugin, WeightedRetrieverPlugin

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 5, tzinfo=UTC)


def _memory(memory_id: str, *, text: str = "atlas retrieval query") -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=_NOW,
        observed_at=_NOW,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


@dataclass
class _StubMemoryStore:
    """In-memory stub that implements MemoryStore."""

    _store: dict[str, MemoryAtom] = field(default_factory=dict)

    def put(self, memory: MemoryAtom) -> None:
        self._store[memory.memory_id] = memory

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._store.get(memory_id)

    def list(self) -> list[MemoryAtom]:
        return list(self._store.values())


@dataclass
class _StubVectorStore:
    """Minimal VectorStore that returns pre-set matches."""

    _matches: list[VectorMatch] = field(default_factory=list)
    _upserted: list[tuple[str, str]] = field(default_factory=list)

    def upsert(self, memory_id: str, text: str) -> None:
        self._upserted.append((memory_id, text))

    def search(self, query: str, *, limit: int = 5) -> Sequence[VectorMatch]:
        return self._matches[:limit]


def _make_retriever(
    memory_store: _StubMemoryStore,
    *,
    token_budget: int = 500,
) -> WeightedRetriever:
    profile = WeightProfile(
        name="test",
        semantic_similarity=1.0,
        vector_similarity=0.0,
        graph_proximity=0.0,
        recency=0.0,
        salience=0.0,
        trust=0.0,
        reinforcement=0.0,
        modality_match=0.0,
        token_budget=token_budget,
        candidate_limit=8,
    )
    ranker = WeightedRanker(profile=profile, now_provider=lambda: _NOW)
    candidate_generator = RetrievalCandidateGenerator(memory_store=memory_store)
    return WeightedRetriever(
        candidate_generator=candidate_generator,
        ranker=ranker,
        profile=profile,
        memory_store=memory_store,
    )


# ---------------------------------------------------------------------------
# Issue #160 — access_count writeback
# ---------------------------------------------------------------------------


def test_access_count_incremented_after_one_retrieval() -> None:
    store = _StubMemoryStore()
    m = _memory("mem-1", text="atlas retrieval query")
    store.put(m)
    retriever = _make_retriever(store)

    retriever.retrieve("atlas retrieval query", top_k=1)

    retrieved = store.get("mem-1")
    assert retrieved is not None
    assert retrieved.retrieval.access_count == 1


def test_access_count_incremented_after_two_retrievals() -> None:
    store = _StubMemoryStore()
    m = _memory("mem-1", text="atlas retrieval query")
    store.put(m)
    retriever = _make_retriever(store)

    retriever.retrieve("atlas retrieval query", top_k=1)
    retriever.retrieve("atlas retrieval query", top_k=1)

    retrieved = store.get("mem-1")
    assert retrieved is not None
    assert retrieved.retrieval.access_count == 2


def test_last_accessed_at_is_set_after_retrieval() -> None:
    store = _StubMemoryStore()
    store.put(_memory("mem-1"))
    retriever = _make_retriever(store)

    retriever.retrieve("atlas retrieval query", top_k=1)

    retrieved = store.get("mem-1")
    assert retrieved is not None
    assert retrieved.retrieval.last_accessed_at is not None


def test_write_back_skipped_when_memory_store_is_none() -> None:
    """WeightedRetriever without a memory_store does not crash."""
    store = _StubMemoryStore()
    m = _memory("mem-1", text="atlas retrieval query")
    store.put(m)

    profile = get_weight_profile("balanced")
    ranker = WeightedRanker(profile=profile, now_provider=lambda: _NOW)
    candidate_generator = RetrievalCandidateGenerator(memory_store=store)
    retriever = WeightedRetriever(
        candidate_generator=candidate_generator,
        ranker=ranker,
        profile=profile,
        memory_store=None,
    )

    bundle = retriever.retrieve("atlas retrieval query", top_k=1)
    assert len(bundle.memories) >= 1
    # No writeback occurred — original record still has access_count == 0
    original = store.get("mem-1")
    assert original is not None
    assert original.retrieval.access_count == 0


# ---------------------------------------------------------------------------
# Issue #161 — representation_store wiring
# ---------------------------------------------------------------------------


def test_ingestor_upserts_to_representation_store_when_set() -> None:
    from cellin.ingest.pipeline import CanonicalIngestor
    from cellin.stores import InMemoryGraphStore, InMemoryMemoryStore

    repr_store = _StubVectorStore()
    vector_store = _StubVectorStore()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=InMemoryGraphStore(),
        memory_store=InMemoryMemoryStore(),
        vector_store=vector_store,
        representation_store=repr_store,
    )

    from cellin.core import Artifact

    artifact = Artifact(
        artifact_id="art-1",
        modality=Modality.TEXT,
        content="hello world",
        provenance=Provenance(source_id="art-1", source_type="test"),
        created_at=_NOW,
    )
    ingestor.ingest([artifact])

    assert ("art-1", "hello world") in repr_store._upserted


def test_ingestor_skips_representation_store_when_none() -> None:
    from cellin.ingest.pipeline import CanonicalIngestor
    from cellin.stores import InMemoryGraphStore, InMemoryMemoryStore

    vector_store = _StubVectorStore()
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=InMemoryGraphStore(),
        memory_store=InMemoryMemoryStore(),
        vector_store=vector_store,
        representation_store=None,
    )

    from cellin.core import Artifact

    artifact = Artifact(
        artifact_id="art-2",
        modality=Modality.TEXT,
        content="hello world",
        provenance=Provenance(source_id="art-2", source_type="test"),
        created_at=_NOW,
    )
    ingestor.ingest([artifact])

    # No representation_store - should work without errors, vector_store still upserted
    assert ("art-2", "hello world") in vector_store._upserted


def test_retriever_representation_store_wires_to_candidate_generator() -> None:
    """representation_store is injected into candidate_generator.vector_store when None."""
    store = _StubMemoryStore()
    store.put(_memory("mem-1"))

    repr_store = _StubVectorStore(_matches=[VectorMatch(memory_id="mem-1", score=0.9)])
    profile = get_weight_profile("balanced")
    ranker = WeightedRanker(profile=profile, now_provider=lambda: _NOW)
    candidate_generator = RetrievalCandidateGenerator(memory_store=store, vector_store=None)
    WeightedRetriever(
        candidate_generator=candidate_generator,
        ranker=ranker,
        profile=profile,
        representation_store=repr_store,
    )

    # After construction, the representation_store should be wired to candidate_generator
    assert candidate_generator.vector_store is repr_store


def test_retriever_representation_store_does_not_override_existing_vector_store() -> None:
    """representation_store must not override an existing candidate_generator.vector_store."""
    store = _StubMemoryStore()
    existing_vs = _StubVectorStore()
    repr_store = _StubVectorStore()

    profile = get_weight_profile("balanced")
    ranker = WeightedRanker(profile=profile, now_provider=lambda: _NOW)
    candidate_generator = RetrievalCandidateGenerator(memory_store=store, vector_store=existing_vs)
    WeightedRetriever(
        candidate_generator=candidate_generator,
        ranker=ranker,
        profile=profile,
        representation_store=repr_store,
    )

    # Existing vector_store must be preserved
    assert candidate_generator.vector_store is existing_vs


# ---------------------------------------------------------------------------
# Issue #168 — WeightedRankerPlugin and WeightedRetrieverPlugin
# ---------------------------------------------------------------------------


def test_weighted_ranker_plugin_is_discoverable_via_registry() -> None:
    registry = PluginRegistry()
    plugin = WeightedRankerPlugin()
    manifest = registry.register(plugin)

    assert manifest.plugin_id == "weighted-ranker"
    assert Capability.RANKER in manifest.capabilities
    assert registry.plugins_for(Capability.RANKER) == (plugin,)


def test_weighted_retriever_plugin_is_discoverable_via_registry() -> None:
    registry = PluginRegistry()
    plugin = WeightedRetrieverPlugin()
    manifest = registry.register(plugin)

    assert manifest.plugin_id == "weighted-retriever"
    assert Capability.RETRIEVER in manifest.capabilities
    assert registry.plugins_for(Capability.RETRIEVER) == (plugin,)


def test_weighted_ranker_plugin_instantiates_ranker_on_start() -> None:
    from cellin.ranking.weighted import WeightedRanker

    plugin = WeightedRankerPlugin()
    registry = PluginRegistry()
    registry.register(plugin)

    assert isinstance(plugin.ranker, WeightedRanker)


def test_weighted_retriever_plugin_instantiates_retriever_on_start() -> None:
    from cellin.retrieval.service import WeightedRetriever

    plugin = WeightedRetrieverPlugin()
    registry = PluginRegistry()
    registry.register(plugin)

    assert isinstance(plugin.retriever, WeightedRetriever)


def test_weighted_ranker_plugin_respects_profile_setting() -> None:
    from cellin.core.contracts import PluginContext, RuntimeConfig
    from cellin.ranking.weighted import WeightedRanker

    plugin = WeightedRankerPlugin()
    ctx = PluginContext(
        runtime_id="test",
        config=RuntimeConfig(),
        plugin_settings={"profile": "recency_sensitive"},
    )
    plugin.configure(ctx)
    plugin.start()

    assert isinstance(plugin.ranker, WeightedRanker)
    assert plugin.ranker.profile.name == "recency_sensitive"  # type: ignore[union-attr]


def test_weighted_ranker_plugin_stop_is_noop() -> None:
    plugin = WeightedRankerPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    # stop() should not raise
    plugin.stop()


def test_weighted_retriever_plugin_stop_is_noop() -> None:
    plugin = WeightedRetrieverPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    plugin.stop()
