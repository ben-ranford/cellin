"""Workspace config and trace helpers for the Cellin CLI."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cellin.core import TraceEvent
from cellin.core.models import JSONValue
from cellin.runtime.storage import StorageBackendConfig, StorageConfig

DEFAULT_CONFIG_FILENAME = "cellin.json"
DEFAULT_RUNTIME_ID = "cellin-cli"
DEFAULT_DATABASE_FILENAME = "cellin.sqlite"
DEFAULT_TRACE_FILENAME = "traces.jsonl"
DEFAULT_PROFILE_NAME = "balanced"


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Serializable CLI workspace config."""

    runtime_id: str = DEFAULT_RUNTIME_ID
    trace_path: str = DEFAULT_TRACE_FILENAME
    profile_name: str = DEFAULT_PROFILE_NAME
    database_path: str | None = None
    storage: StorageConfig | None = None


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """Resolved config with absolute storage paths."""

    config_path: Path
    runtime_id: str
    storage: StorageConfig
    trace_path: Path
    profile_name: str


def _as_str(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _coerce_storage_role(
    role: str,
    raw_config: object,
    *,
    default_backend: str,
    fallback_database_path: str,
) -> StorageBackendConfig:
    if raw_config is None:
        if default_backend == "sqlite":
            return StorageBackendConfig(default_backend, fallback_database_path)
        return StorageBackendConfig(default_backend)

    if not isinstance(raw_config, Mapping):
        raise ValueError(f"`{role}` storage config must be an object.")

    backend_raw = raw_config.get("backend")
    if backend_raw is not None and not isinstance(backend_raw, str):
        raise ValueError(f"`{role}` storage backend must be a string.")

    backend = backend_raw if isinstance(backend_raw, str) else default_backend
    database_path_raw = raw_config.get("database_path")
    if database_path_raw is not None and not isinstance(database_path_raw, str):
        raise ValueError(f"`{role}` storage database_path must be a string.")

    if backend == "sqlite":
        resolved_path: str | None = database_path_raw or fallback_database_path
    else:
        resolved_path = database_path_raw
    if backend == "sqlite" and resolved_path == "":
        resolved_path = fallback_database_path

    return StorageBackendConfig(
        backend=backend,
        database_path=resolved_path,
    )


def _coerce_storage_config(raw: Mapping[str, object]) -> StorageConfig:
    legacy_database_path = raw.get("database_path")
    fallback_database_path = (
        legacy_database_path if isinstance(legacy_database_path, str) else DEFAULT_DATABASE_FILENAME
    )
    raw_storage = raw.get("storage")
    if raw_storage is None:
        if isinstance(legacy_database_path, str):
            return StorageConfig.with_sqlite_preset(legacy_database_path)
        return StorageConfig.with_in_memory_preset()

    if not isinstance(raw_storage, Mapping):
        raise ValueError("`storage` must be an object.")

    return StorageConfig(
        memory=_coerce_storage_role(
            "memory",
            raw_storage.get("memory"),
            default_backend="in_memory",
            fallback_database_path=fallback_database_path,
        ),
        graph=_coerce_storage_role(
            "graph",
            raw_storage.get("graph"),
            default_backend="in_memory",
            fallback_database_path=fallback_database_path,
        ),
        vector=_coerce_storage_role(
            "vector",
            raw_storage.get("vector"),
            default_backend="in_memory_vector_index",
            fallback_database_path=fallback_database_path,
        ),
        representation=_coerce_storage_role(
            "representation",
            raw_storage.get("representation"),
            default_backend="in_memory_vector_index",
            fallback_database_path=fallback_database_path,
        ),
    )


def init_workspace(target: Path) -> Path:
    """Create a workspace config file if it does not exist."""

    config_path = target if target.suffix == ".json" else target / DEFAULT_CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        defaults = WorkspaceConfig(
            storage=StorageConfig.with_in_memory_preset(),
        )
        payload = asdict(defaults)
        payload.pop("database_path", None)
        config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return config_path


def load_workspace(config_path: Path) -> ResolvedWorkspace:
    """Load a workspace config and resolve relative paths."""

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("Workspace config must be a JSON object.")

    storage = _coerce_storage_config(raw)

    return ResolvedWorkspace(
        config_path=config_path,
        runtime_id=_as_str(raw.get("runtime_id"), default=DEFAULT_RUNTIME_ID),
        storage=storage,
        trace_path=(
            config_path.parent / _as_str(raw.get("trace_path"), default=DEFAULT_TRACE_FILENAME)
        ).resolve(),
        profile_name=_as_str(raw.get("profile_name"), default=DEFAULT_PROFILE_NAME),
    )


def append_trace(
    workspace: ResolvedWorkspace, *, name: str, payload: dict[str, JSONValue]
) -> TraceEvent:
    """Append a JSONL trace event for later inspection."""

    event = TraceEvent(name=name, timestamp=datetime.now(UTC), payload=payload)
    workspace.trace_path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "name": event.name,
        "timestamp": event.timestamp.isoformat(),
        "payload": event.payload,
    }
    with workspace.trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True))
        handle.write("\n")
    return event


def read_traces(workspace: ResolvedWorkspace, *, limit: int) -> tuple[TraceEvent, ...]:
    """Read the last N trace events from the workspace trace log."""

    if limit <= 0:
        return ()
    if not workspace.trace_path.exists():
        return ()

    lines = workspace.trace_path.read_text(encoding="utf-8").splitlines()
    events: list[TraceEvent] = []
    for line in lines[-limit:]:
        raw = json.loads(line)
        events.append(
            TraceEvent(
                name=str(raw["name"]),
                timestamp=datetime.fromisoformat(str(raw["timestamp"])),
                payload=dict(raw.get("payload", {})),
            )
        )
    return tuple(events)
