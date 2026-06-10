"""Unit tests for the MCP server adapter surface."""

from __future__ import annotations

import asyncio
import importlib
import json
import runpy
import sys
import types
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest

import cellin.mcp.server as mcp_server
import cellin.mcp.tools as mcp_tools
from cellin.core import DecayState, MemoryAtom, MemoryKind, Modality, Provenance
from cellin.dreaming.models import DreamMemoryChange
from cellin.mcp.server import startup_check, tool_schemas
from cellin.mcp.subjects import SubjectRegistry
from cellin.mcp.tools import CellinMCPTools, dispatch_tool

_NOW = datetime(2026, 6, 11, tzinfo=UTC)


def test_tool_schemas_expose_expected_core_tools() -> None:
    assert {schema["name"] for schema in tool_schemas()} == {
        "ingest_memory",
        "retrieve_memories",
        "run_dream",
        "inspect_graph",
        "list_memories",
    }


def test_dispatch_tool_routes_to_runtime_tool_without_sdk_dependency() -> None:
    tools = Mock(spec=CellinMCPTools)
    tools.retrieve_memories.return_value = {
        "subject": "atlas",
        "query": "launch",
        "total_score": 0.0,
        "memories": [],
    }

    payload = dispatch_tool(
        cast(CellinMCPTools, tools),
        "retrieve_memories",
        {"subject": "atlas", "query": "launch"},
    )

    assert payload["subject"] == "atlas"
    tools.retrieve_memories.assert_called_once_with(
        subject="atlas",
        query="launch",
        limit=None,
    )


def test_startup_check_reports_registry_paths(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path, data_directory="subjects")

    payload = startup_check(registry)

    assert payload["status"] == "ok"
    assert payload["workspace_root"] == str(tmp_path.resolve())
    assert payload["data_directory"] == str((tmp_path / "subjects").resolve())


def test_load_mcp_sdk_reports_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(_: str) -> types.ModuleType:
        raise ImportError("missing")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    with pytest.raises(RuntimeError, match=r"cellin\[mcp\]"):
        mcp_server._load_mcp_sdk()


def test_serve_stdio_wraps_registry_in_runtime_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, CellinMCPTools] = {}

    async def fake_serve(tools: CellinMCPTools) -> None:
        await asyncio.sleep(0)
        captured["tools"] = tools

    registry = SubjectRegistry(workspace_root=tmp_path)
    monkeypatch.setattr(mcp_server, "_serve_stdio_async", fake_serve)

    mcp_server.serve_stdio(registry)

    assert captured["tools"].subject_registry is registry


def test_serve_stdio_async_registers_sdk_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {}

    class FakeServer:
        def __init__(self, name: str) -> None:
            state["name"] = name
            state["server"] = self

        def list_tools(self) -> object:
            def decorator(func: object) -> object:
                state["list_tools_handler"] = func
                return func

            return decorator

        def call_tool(self) -> object:
            def decorator(func: object) -> object:
                state["call_tool_handler"] = func
                return func

            return decorator

        def create_initialization_options(self) -> dict[str, str]:
            return {"init": "ok"}

        async def run(self, read_stream: object, write_stream: object, options: object) -> None:
            state["run_args"] = (read_stream, write_stream, options)
            listed = await cast(Any, state["list_tools_handler"])()
            state["listed"] = listed
            contents = await cast(Any, state["call_tool_handler"])(
                "retrieve_memories",
                {"subject": "atlas", "query": "launch"},
            )
            state["contents"] = contents

    class FakeStdio:
        async def __aenter__(self) -> tuple[str, str]:
            return ("read", "write")

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeTool:
        def __init__(self, **kwargs: object) -> None:
            self.name = kwargs["name"]

    class FakeTextContent:
        def __init__(self, *, type: str, text: str) -> None:
            self.type = type
            self.text = text

    fake_server_module = types.ModuleType("mcp.server")
    fake_server_module.Server = FakeServer  # type: ignore[attr-defined]
    fake_stdio_module = types.ModuleType("mcp.server.stdio")
    fake_stdio_module.stdio_server = FakeStdio  # type: ignore[attr-defined]
    fake_types_module = types.ModuleType("mcp.types")
    fake_types_module.Tool = FakeTool  # type: ignore[attr-defined]
    fake_types_module.TextContent = FakeTextContent  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", fake_stdio_module)
    monkeypatch.setitem(sys.modules, "mcp.types", fake_types_module)

    tools = Mock(spec=CellinMCPTools)
    tools.retrieve_memories.return_value = {
        "subject": "atlas",
        "query": "launch",
        "total_score": 1.0,
        "memories": [],
    }

    asyncio.run(mcp_server._serve_stdio_async(cast(CellinMCPTools, tools)))

    assert state["name"] == "cellin"
    assert state["run_args"] == ("read", "write", {"init": "ok"})
    assert {tool.name for tool in cast(list[FakeTool], state["listed"])} == {
        "ingest_memory",
        "retrieve_memories",
        "run_dream",
        "inspect_graph",
        "list_memories",
    }
    [content] = cast(list[FakeTextContent], state["contents"])
    assert content.type == "text"
    assert json.loads(content.text)["query"] == "launch"


def test_main_check_prints_startup_payload(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mcp_server.main(["--workspace-root", str(tmp_path), "--data-dir", "subjects", "--check"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["workspace_root"] == str(tmp_path.resolve())


def test_main_serves_stdio_when_check_is_not_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, SubjectRegistry] = {}

    def fake_serve(registry: SubjectRegistry) -> None:
        captured["registry"] = registry

    monkeypatch.setattr(mcp_server, "serve_stdio", fake_serve)

    mcp_server.main(["--workspace-root", str(tmp_path), "--data-dir", "subjects"])

    assert captured["registry"].workspace_root == tmp_path.resolve()


def test_module_entrypoint_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    def fake_main() -> None:
        called.append(True)

    monkeypatch.setattr(mcp_server, "main", fake_main)

    runpy.run_module("cellin.mcp.__main__", run_name="__main__")

    assert called == [True]


def test_runtime_tools_reject_empty_memory_text(tmp_path: Path) -> None:
    tools = CellinMCPTools(SubjectRegistry(workspace_root=tmp_path))

    with pytest.raises(ValueError, match="non-empty"):
        tools.ingest_memory("atlas", "   ")


def test_runtime_tools_use_default_retrieval_limit(tmp_path: Path) -> None:
    tools = CellinMCPTools(SubjectRegistry(workspace_root=tmp_path))

    payload = tools.retrieve_memories("atlas", "launch plan")

    assert payload["subject"] == "atlas"
    assert payload["memories"] == []


def test_runtime_tools_run_pending_and_empty_strategy_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeDreamRunner:
        def run_pending(self) -> tuple[()]:
            return ()

        def run_strategy(self, _: str) -> None:
            return None

    monkeypatch.setattr(mcp_tools, "_bundle_dream_runner", lambda _: FakeDreamRunner())
    tools = CellinMCPTools(SubjectRegistry(workspace_root=tmp_path))

    pending = tools.run_dream("atlas")
    explicit = tools.run_dream("atlas", strategy="decay_archival")

    assert pending["strategy"] == "pending"
    assert pending["affected_count"] == 0
    assert explicit["strategy"] == "decay_archival"
    assert explicit["runs"] == []


def test_memory_change_payload_classifies_non_created_changes() -> None:
    before = _memory("memory-1")
    archived = replace(before, decay=DecayState(archived=True))
    updated = replace(before, trust_score=0.7)

    assert (
        mcp_tools._memory_change_payload(
            DreamMemoryChange(memory_id="memory-1", before=before, after=None)
        )["type"]
        == "deleted"
    )
    assert (
        mcp_tools._memory_change_payload(
            DreamMemoryChange(memory_id="memory-1", before=before, after=archived)
        )["type"]
        == "archived"
    )
    assert (
        mcp_tools._memory_change_payload(
            DreamMemoryChange(memory_id="memory-1", before=before, after=updated)
        )["type"]
        == "updated"
    )


@pytest.mark.parametrize(
    ("name", "arguments", "method_name", "expected_kwargs"),
    [
        (
            "ingest_memory",
            {
                "subject": "atlas",
                "text": "Launch note",
                "topic": "launch",
                "modality": "markdown",
                "metadata": {"source": "fixture"},
            },
            "ingest_memory",
            {
                "subject": "atlas",
                "text": "Launch note",
                "topic": "launch",
                "modality": "markdown",
                "metadata": {"source": "fixture"},
            },
        ),
        (
            "run_dream",
            {"subject": "atlas", "strategy": "abstraction"},
            "run_dream",
            {"subject": "atlas", "strategy": "abstraction"},
        ),
        (
            "inspect_graph",
            {"subject": "atlas", "memory_id": "memory-1"},
            "inspect_graph",
            {"subject": "atlas", "memory_id": "memory-1"},
        ),
        (
            "list_memories",
            {"subject": "atlas", "topic": "launch", "archived": False},
            "list_memories",
            {"subject": "atlas", "topic": "launch", "archived": False},
        ),
    ],
)
def test_dispatch_tool_routes_supported_operations(
    name: str,
    arguments: dict[str, object],
    method_name: str,
    expected_kwargs: dict[str, object],
) -> None:
    tools = Mock(spec=CellinMCPTools)
    getattr(tools, method_name).return_value = {"subject": "atlas"}

    payload = dispatch_tool(cast(CellinMCPTools, tools), name, arguments)

    assert payload == {"subject": "atlas"}
    getattr(tools, method_name).assert_called_once_with(**expected_kwargs)


def test_dispatch_tool_rejects_unknown_tool_name() -> None:
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        dispatch_tool(Mock(spec=CellinMCPTools), "missing_tool", {"subject": "atlas"})


def _memory(memory_id: str) -> MemoryAtom:
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text="Launch memory",
        provenance=Provenance(source_id="fixture", source_type="test"),
        modality=Modality.TEXT,
        created_at=_NOW,
    )
