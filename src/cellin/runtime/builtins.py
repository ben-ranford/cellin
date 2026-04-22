"""Built-in plugins used by the runtime and contract tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cellin.__about__ import __version__
from cellin.core.contracts import Capability, PluginContext, PluginManifest
from cellin.core.models import JSONValue, TraceEvent


@dataclass(slots=True)
class InMemoryTraceSinkPlugin:
    """A minimal built-in plugin used to exercise runtime registration."""

    events: list[TraceEvent] = field(default_factory=list)
    context: PluginContext | None = None
    started: bool = False

    manifest = PluginManifest(
        plugin_id="in-memory-trace-sink",
        version=__version__,
        capabilities=(Capability.TRACE_SINK,),
        display_name="In-memory trace sink",
        description="Stores trace events in memory for tests and local development.",
    )

    def configure(self, context: PluginContext) -> None:
        self.context = context

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def drain(self) -> tuple[TraceEvent, ...]:
        """Return a snapshot of recorded events."""

        return tuple(self.events)


@dataclass(slots=True)
class WeightedRankerPlugin:
    """Built-in plugin that exposes WeightedRanker as a RANKER capability."""

    _settings: Mapping[str, JSONValue] = field(default_factory=dict)
    _ranker: object = field(default=None, init=False, repr=False)

    manifest = PluginManifest(
        plugin_id="weighted-ranker",
        version=__version__,
        capabilities=(Capability.RANKER,),
        display_name="Weighted ranker",
        description="Deterministic explainable weighted ranking over memory atoms.",
    )

    def configure(self, context: PluginContext) -> None:
        self._settings = context.plugin_settings

    def start(self) -> None:
        from cellin.ranking.profiles import get_weight_profile
        from cellin.ranking.weighted import WeightedRanker

        profile_name = self._settings.get("profile", "balanced")
        self._ranker = WeightedRanker(profile=get_weight_profile(str(profile_name)))

    def stop(self) -> None:
        pass

    @property
    def ranker(self) -> object:
        """Return the configured WeightedRanker instance."""
        return self._ranker


@dataclass(slots=True)
class WeightedRetrieverPlugin:
    """Built-in plugin that exposes WeightedRetriever as a RETRIEVER capability."""

    _settings: Mapping[str, JSONValue] = field(default_factory=dict)
    _retriever: object = field(default=None, init=False, repr=False)

    manifest = PluginManifest(
        plugin_id="weighted-retriever",
        version=__version__,
        capabilities=(Capability.RETRIEVER,),
        display_name="Weighted retriever",
        description="Assembles explainable memory bundles from candidate memory atoms.",
    )

    def configure(self, context: PluginContext) -> None:
        self._settings = context.plugin_settings

    def start(self) -> None:
        from cellin.ranking.profiles import get_weight_profile
        from cellin.ranking.weighted import WeightedRanker
        from cellin.retrieval.candidate_generation import RetrievalCandidateGenerator
        from cellin.retrieval.service import WeightedRetriever
        from cellin.stores import InMemoryMemoryStore

        profile_name = self._settings.get("profile", "balanced")
        profile = get_weight_profile(str(profile_name))
        memory_store = InMemoryMemoryStore()
        candidate_generator = RetrievalCandidateGenerator(memory_store=memory_store)
        ranker = WeightedRanker(profile=profile)
        self._retriever = WeightedRetriever(
            candidate_generator=candidate_generator,
            ranker=ranker,
            profile=profile,
        )

    def stop(self) -> None:
        pass

    @property
    def retriever(self) -> object:
        """Return the configured WeightedRetriever instance."""
        return self._retriever
