"""Built-in plugins used by the runtime and contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from cellin.core.contracts import Capability, PluginContext, PluginManifest
from cellin.core.models import TraceEvent


@dataclass(slots=True)
class InMemoryTraceSinkPlugin:
    """A minimal built-in plugin used to exercise runtime registration."""

    events: list[TraceEvent] = field(default_factory=list)
    context: PluginContext | None = None
    started: bool = False

    manifest = PluginManifest(
        plugin_id="in-memory-trace-sink",
        version="0.1.0",
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
