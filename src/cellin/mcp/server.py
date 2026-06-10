"""MCP SDK adapter for the Cellin tool surface."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
from pathlib import Path
from typing import Any

from cellin.core.models import JSONValue
from cellin.mcp.subjects import SubjectRegistry
from cellin.mcp.tools import CellinMCPTools, dispatch_tool

type JSONSchemaProperty = dict[str, object]


def _json_schema(
    properties: dict[str, JSONSchemaProperty],
    required: list[str],
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_schemas() -> list[dict[str, object]]:
    """Return MCP tool definitions in SDK-neutral dictionary form."""

    subject: JSONSchemaProperty = {"type": "string", "description": "Slug-safe subject ID."}
    return [
        {
            "name": "ingest_memory",
            "description": "Ingest a memory atom into a subject-scoped Cellin store.",
            "inputSchema": _json_schema(
                {
                    "subject": subject,
                    "text": {"type": "string"},
                    "topic": {"type": "string"},
                    "modality": {
                        "type": "string",
                        "enum": ["text", "markdown", "chat", "json"],
                        "default": "text",
                    },
                    "metadata": {"type": "object"},
                },
                ["subject", "text"],
            ),
        },
        {
            "name": "retrieve_memories",
            "description": "Retrieve scored memories for a subject and query.",
            "inputSchema": _json_schema(
                {
                    "subject": subject,
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 0, "default": 5},
                },
                ["subject", "query"],
            ),
        },
        {
            "name": "run_dream",
            "description": "Run pending dream work or a named dream strategy for a subject.",
            "inputSchema": _json_schema(
                {
                    "subject": subject,
                    "strategy": {
                        "type": "string",
                        "enum": [
                            "deduplication",
                            "contradiction_repair",
                            "abstraction",
                            "decay_archival",
                        ],
                    },
                },
                ["subject"],
            ),
        },
        {
            "name": "inspect_graph",
            "description": "Inspect a subject memory graph or one memory's neighbors.",
            "inputSchema": _json_schema(
                {
                    "subject": subject,
                    "memory_id": {"type": "string"},
                },
                ["subject"],
            ),
        },
        {
            "name": "list_memories",
            "description": "List subject memories with optional topic and archive filters.",
            "inputSchema": _json_schema(
                {
                    "subject": subject,
                    "topic": {"type": "string"},
                    "archived": {"type": "boolean"},
                },
                ["subject"],
            ),
        },
    ]


def _load_mcp_sdk() -> tuple[Any, Any, Any]:
    try:
        server_module = importlib.import_module("mcp.server")
        stdio_module = importlib.import_module("mcp.server.stdio")
        types_module = importlib.import_module("mcp.types")
    except ImportError as exc:
        raise RuntimeError(
            "The MCP server requires the optional dependency set. Install with `cellin[mcp]`."
        ) from exc
    return server_module.Server, stdio_module.stdio_server, types_module


async def _serve_stdio_async(tools: CellinMCPTools) -> None:
    server_cls, stdio_server, types_module = _load_mcp_sdk()
    server = server_cls("cellin")

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def handle_list_tools() -> list[Any]:
        tool_cls = types_module.Tool
        return [tool_cls(**schema) for schema in tool_schemas()]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def handle_call_tool(
        name: str,
        arguments: dict[str, Any] | None,
    ) -> list[Any]:
        text_content_cls = types_module.TextContent
        payload = dispatch_tool(tools, name, arguments)
        return [text_content_cls(type="text", text=json.dumps(payload, sort_keys=True))]

    async with stdio_server() as streams:
        read_stream, write_stream = streams
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def serve_stdio(subject_registry: SubjectRegistry) -> None:
    """Start the MCP stdio server."""

    asyncio.run(_serve_stdio_async(CellinMCPTools(subject_registry)))


def startup_check(subject_registry: SubjectRegistry) -> dict[str, JSONValue]:
    """Return a lightweight startup health payload."""

    return {
        "status": "ok",
        "workspace_root": str(subject_registry.workspace_root),
        "data_directory": str(subject_registry.data_directory),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Cellin as an MCP server.")
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    registry = SubjectRegistry(
        workspace_root=Path(args.workspace_root),
        data_directory=Path(args.data_dir),
    )
    if args.check:
        print(json.dumps(startup_check(registry), sort_keys=True))
    else:
        serve_stdio(registry)
