"""Plugin registry and entry-point loading for the Cellin runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import metadata
from typing import cast

from cellin.core.contracts import Capability, Plugin, PluginContext, PluginManifest, RuntimeConfig


def _ensure_plugin(candidate: object) -> Plugin:
    manifest = getattr(candidate, "manifest", None)
    if not isinstance(manifest, PluginManifest):
        raise TypeError("Plugin candidate must expose a PluginManifest as `manifest`.")

    for method_name in ("configure", "start", "stop"):
        method = getattr(candidate, method_name, None)
        if not callable(method):
            raise TypeError(f"Plugin candidate is missing lifecycle method `{method_name}`.")

    return cast(Plugin, candidate)


def _instantiate_plugin(loaded: object) -> Plugin:
    should_instantiate = isinstance(loaded, type) or (
        callable(loaded) and not hasattr(loaded, "manifest")
    )
    candidate = cast(Callable[[], object], loaded)() if should_instantiate else loaded

    return _ensure_plugin(candidate)


class PluginRegistry:
    """Runtime registry for built-in and entry-point plugins."""

    def __init__(
        self,
        *,
        runtime_id: str = "cellin-runtime",
        config: RuntimeConfig | None = None,
        entrypoint_group: str = "cellin.plugins",
    ) -> None:
        self.runtime_id = runtime_id
        self.config = config or RuntimeConfig()
        self.entrypoint_group = entrypoint_group
        self._plugins: dict[str, Plugin] = {}
        self._manifests: dict[str, PluginManifest] = {}

    def register(self, plugin: Plugin, *, context: PluginContext | None = None) -> PluginManifest:
        """Register, configure, and start a plugin."""

        validated_plugin = _ensure_plugin(plugin)
        plugin_id = validated_plugin.manifest.plugin_id

        if plugin_id in self._plugins:
            raise ValueError(f"Plugin `{plugin_id}` is already registered.")

        resolved_context = context or PluginContext(
            runtime_id=self.runtime_id,
            config=self.config,
            plugin_settings=self.config.plugins.get(plugin_id, {}),
        )
        validated_plugin.configure(resolved_context)
        validated_plugin.start()
        self._plugins[plugin_id] = validated_plugin
        self._manifests[plugin_id] = validated_plugin.manifest
        return validated_plugin.manifest

    def get(self, plugin_id: str) -> Plugin:
        """Return a single registered plugin."""

        return self._plugins[plugin_id]

    def manifests(self, capability: Capability | None = None) -> tuple[PluginManifest, ...]:
        """Return plugin manifests, optionally filtered by capability."""

        manifests = tuple(self._manifests.values())
        if capability is None:
            return manifests

        return tuple(manifest for manifest in manifests if capability in manifest.capabilities)

    def plugins_for(self, capability: Capability) -> tuple[Plugin, ...]:
        """Return registered plugins that expose a given capability."""

        return tuple(
            plugin
            for plugin_id, plugin in self._plugins.items()
            if capability in self._manifests[plugin_id].capabilities
        )

    def load_entry_points(self, *, group: str | None = None) -> tuple[str, ...]:
        """Discover and register plugins from Python entry points."""

        entry_points = metadata.entry_points()
        target_group = group or self.entrypoint_group
        selected = entry_points.select(group=target_group)
        loaded_ids: list[str] = []

        for entry_point in selected:
            plugin = _instantiate_plugin(entry_point.load())
            manifest = self.register(plugin)
            loaded_ids.append(manifest.plugin_id)

        return tuple(loaded_ids)

    def shutdown(self) -> None:
        """Stop registered plugins in reverse order."""

        for plugin_id in reversed(tuple(self._plugins.keys())):
            self._plugins[plugin_id].stop()

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        """Return plugin ids in registration order."""

        return tuple(self._plugins.keys())

    def __iter__(self) -> Iterable[Plugin]:
        """Iterate registered plugins in registration order."""

        return iter(self._plugins.values())
