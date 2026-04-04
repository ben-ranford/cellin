"""Contract tests for the Cellin plugin registry."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cellin.core import Capability, PluginContext, RuntimeConfig
from cellin.runtime import InMemoryTraceSinkPlugin, PluginRegistry


def test_registry_registers_builtin_plugin_and_filters_capabilities() -> None:
    config = RuntimeConfig(
        plugins={"in-memory-trace-sink": {"buffer_size": 8}},
        environment={"CELLIN_ENV": "test"},
    )
    registry = PluginRegistry(runtime_id="cellin-test", config=config)
    plugin = InMemoryTraceSinkPlugin()

    manifest = registry.register(plugin)

    assert manifest.plugin_id == "in-memory-trace-sink"
    assert registry.plugin_ids == ("in-memory-trace-sink",)
    assert registry.plugins_for(Capability.TRACE_SINK) == (plugin,)
    assert plugin.started is True
    assert plugin.context == PluginContext(
        runtime_id="cellin-test",
        config=config,
        plugin_settings={"buffer_size": 8},
    )

    registry.shutdown()

    assert plugin.started is False


def test_registry_rejects_duplicate_plugin_ids() -> None:
    registry = PluginRegistry()

    registry.register(InMemoryTraceSinkPlugin())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(InMemoryTraceSinkPlugin())


@dataclass
class FakeEntryPoint:
    """Simple stand-in for Python package entry points."""

    name: str
    group: str

    def load(self) -> type[InMemoryTraceSinkPlugin]:
        return InMemoryTraceSinkPlugin


class FakeEntryPoints(list[FakeEntryPoint]):
    """Mimics the entry point API returned by importlib.metadata."""

    def select(self, *, group: str) -> list[FakeEntryPoint]:
        return [entry_point for entry_point in self if entry_point.group == group]


def test_registry_loads_plugins_from_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_entry_points() -> FakeEntryPoints:
        return FakeEntryPoints([FakeEntryPoint(name="trace", group="cellin.plugins")])

    monkeypatch.setattr("cellin.runtime.registry.metadata.entry_points", fake_entry_points)

    registry = PluginRegistry()

    loaded_ids = registry.load_entry_points()

    assert loaded_ids == ("in-memory-trace-sink",)
    assert registry.manifests(Capability.TRACE_SINK)[0].display_name == "In-memory trace sink"
