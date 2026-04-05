"""Workspace config and trace helpers for the Cellin CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cellin.core import TraceEvent
from cellin.core.models import JSONValue

CONFIG_FILE = "cellin.json"


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Serializable CLI workspace config."""

    runtime_id: str = "cellin-cli"
    database_path: str = "cellin.sqlite"
    trace_path: str = "traces.jsonl"
    profile_name: str = "balanced"


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """Resolved config with absolute storage paths."""

    config_path: Path
    runtime_id: str
    database_path: Path
    trace_path: Path
    profile_name: str


def init_workspace(target: Path) -> Path:
    """Create a workspace config file if it does not exist."""

    config_path = target if target.suffix == ".json" else target / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        payload = {
            "runtime_id": "cellin-cli",
            "database_path": "cellin.sqlite",
            "trace_path": "traces.jsonl",
            "profile_name": "balanced",
        }
        config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return config_path


def load_workspace(config_path: Path) -> ResolvedWorkspace:
    """Load a workspace config and resolve relative paths."""

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    workspace = WorkspaceConfig(
        runtime_id=str(raw.get("runtime_id", "cellin-cli")),
        database_path=str(raw.get("database_path", "cellin.sqlite")),
        trace_path=str(raw.get("trace_path", "traces.jsonl")),
        profile_name=str(raw.get("profile_name", "balanced")),
    )
    root = config_path.parent
    return ResolvedWorkspace(
        config_path=config_path,
        runtime_id=workspace.runtime_id,
        database_path=(root / workspace.database_path).resolve(),
        trace_path=(root / workspace.trace_path).resolve(),
        profile_name=workspace.profile_name,
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
