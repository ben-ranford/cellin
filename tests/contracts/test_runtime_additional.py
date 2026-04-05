"""Additional runtime contract coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from cellin.core import Capability, PluginManifest, TraceEvent
from cellin.runtime import InMemoryTraceSinkPlugin, PluginRegistry
from cellin.runtime.registry import _ensure_plugin


def test_trace_sink_plugin_records_and_drains_events() -> None:
    plugin = InMemoryTraceSinkPlugin()
    event = TraceEvent(name="runtime.event", timestamp=datetime(2026, 4, 5, tzinfo=UTC))

    plugin.record(event)

    assert plugin.drain() == (event,)


def test_registry_get_and_iteration_expose_registered_plugins() -> None:
    plugin = InMemoryTraceSinkPlugin()
    registry = PluginRegistry()
    registry.register(plugin)

    assert registry.get(plugin.manifest.plugin_id) is plugin
    assert tuple(registry) == (plugin,)


@dataclass
class MissingManifestPlugin:
    def configure(self, _: object) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


@dataclass
class MissingStopPlugin:
    manifest = PluginManifest(
        plugin_id="missing-stop",
        version="1.0.0",
        capabilities=(Capability.TRACE_SINK,),
    )

    def configure(self, _: object) -> None:
        pass

    def start(self) -> None:
        pass


def test_runtime_plugin_validation_rejects_invalid_candidates() -> None:
    with pytest.raises(TypeError, match="PluginManifest"):
        _ensure_plugin(MissingManifestPlugin())

    with pytest.raises(TypeError, match="stop"):
        _ensure_plugin(MissingStopPlugin())
