"""Integration coverage for the MCP tool surface."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cellin.core.models import JSONValue
from cellin.mcp import CellinMCPTools, SubjectRegistry

_NOW = datetime(2026, 6, 11, tzinfo=UTC)


def _objects(payload: JSONValue) -> list[dict[str, JSONValue]]:
    assert isinstance(payload, list)
    return cast(list[dict[str, JSONValue]], payload)


def _object(payload: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(payload, dict)
    return cast(dict[str, JSONValue], payload)


def test_mcp_tools_exercise_subject_runtime_end_to_end(tmp_path: Path) -> None:
    tools = CellinMCPTools(
        SubjectRegistry(workspace_root=tmp_path),
        now_provider=lambda: _NOW,
    )

    first = tools.ingest_memory(
        "atlas",
        "Atlas launch plan is active and ready.",
        topic="launch",
        metadata={"source": "integration"},
    )
    second = tools.ingest_memory(
        "atlas",
        "Atlas launch plan includes retrieval smoke tests.",
        topic="launch",
    )
    tools.ingest_memory("zephyr", "Separate subject memory.", topic="launch")

    first_memory = _object(first["memory"])
    second_memory = _object(second["memory"])
    assert first_memory["topic"] == "launch"
    assert second_memory["topic"] == "launch"

    listed = tools.list_memories("atlas", topic="launch", archived=False)
    listed_memories = _objects(listed["memories"])
    assert {memory["memory_id"] for memory in listed_memories} == {
        first_memory["memory_id"],
        second_memory["memory_id"],
    }

    retrieved = tools.retrieve_memories("atlas", "launch retrieval plan", limit=2)
    retrieved_memories = _objects(retrieved["memories"])
    assert len(retrieved_memories) == 2
    assert all("score" in memory for memory in retrieved_memories)

    inspected = tools.inspect_graph("atlas", memory_id=cast(str, first_memory["memory_id"]))
    inspected_memory = _object(inspected["memory"])
    assert inspected_memory["memory_id"] == first_memory["memory_id"]

    graph = tools.inspect_graph("atlas")
    assert len(_objects(graph["memories"])) == 2
    assert _objects(graph["edges"]) == []

    dream = tools.run_dream("atlas", strategy="abstraction")
    assert dream["strategy"] == "abstraction"
    assert dream["affected_count"] == 1
    assert _objects(dream["changes"])[0]["type"] == "created"

    updated_graph = tools.inspect_graph("atlas")
    assert len(_objects(updated_graph["edges"])) == 2

    zephyr = tools.list_memories("zephyr")
    assert len(_objects(zephyr["memories"])) == 1
