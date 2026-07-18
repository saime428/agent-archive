from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server


MODES = (
    "call-crash",
    "call-delay",
    "call-results",
    "child-process",
    "default",
    "duplicate-tools",
    "pagination",
    "no-tools",
    "repeat-cursor",
    "init-delay",
    "crash",
    "idle-crash",
    "list-changed",
    "malformed-after-list",
    "list-changed-crash",
    "list-changed-unsafe",
    "large-page",
    "malformed-stdout",
    "invalid-notification",
    "stderr-flood",
    "unique-cursor",
)
SCHEMAS = {
    "valid": {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    },
    "invalid-root": {"type": "string"},
    "invalid-dialect": {"$schema": "https://example.invalid/schema", "type": "object"},
    "keyword-property-names": {
        "type": "object",
        "properties": {
            "$ref": {"type": "string"},
            "$schema": {"type": "string"},
            "pattern": {"type": "string"},
        },
    },
    "external-ref": {
        "type": "object",
        "properties": {"message": {"$ref": "https://example.invalid/message.json"}},
    },
    "external-dynamic-ref": {
        "type": "object",
        "properties": {
            "message": {"$dynamicRef": "https://example.invalid/message.json#message"}
        },
    },
    "missing-ref": {
        "type": "object",
        "properties": {"message": {"$ref": "#/$defs/missing"}},
    },
    "missing-dynamic-ref": {
        "type": "object",
        "properties": {"message": {"$dynamicRef": "#missing"}},
    },
    "regex": {
        "type": "object",
        "properties": {"message": {"type": "string", "pattern": "^(a+)+$"}},
    },
    "env-secret": {
        "type": "object",
    },
    "half-large": {
        "type": "object",
        "description": "h" * (36 * 1024),
    },
    "oversize": {
        "type": "object",
        "description": "x" * (70 * 1024),
    },
    "valid-local-ref": {
        "$defs": {"message": {"type": "string"}},
        "type": "object",
        "properties": {"message": {"$ref": "#/$defs/message"}},
    },
}


def _tool(
    name: str,
    description: str,
    schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema=schema,
        outputSchema=output_schema,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES, default=os.environ.get("MCP_FIXTURE_MODE", "default"))
    parser.add_argument("--delay", type=float, default=float(os.environ.get("MCP_FIXTURE_DELAY", "5")))
    parser.add_argument(
        "--notify-delay",
        type=float,
        default=float(os.environ.get("MCP_FIXTURE_NOTIFY_DELAY", "0.05")),
    )
    parser.add_argument("--start-file", type=Path)
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--call-file", type=Path)
    parser.add_argument("--description-env")
    parser.add_argument("--schema", choices=SCHEMAS, default="valid")
    parser.add_argument("--output-schema", choices=("none", *SCHEMAS), default="none")
    args = parser.parse_args()
    if args.delay < 0 or args.notify_delay < 0:
        parser.error("delays must be non-negative")
    if args.mode == "child-process" and args.child_file is None:
        parser.error("--child-file is required with --mode child-process")
    return args


async def _run(args: argparse.Namespace) -> int:
    if args.start_file is not None:
        with args.start_file.open("a", encoding="ascii") as started:
            started.write(f"{os.getpid()}\n")
    child_process: subprocess.Popen[bytes] | None = None
    if args.mode == "child-process":
        child_process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        args.child_file.write_text(f"{child_process.pid}\n", encoding="ascii")
    if args.mode == "malformed-stdout":
        print(os.environ.get("MCP_FIXTURE_NOISE", "not-json"), flush=True)
    if args.mode == "stderr-flood":
        sys.stderr.write("x" * (200 * 1024))
        sys.stderr.flush()
    if args.mode == "crash":
        return 17

    background_tasks: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(_: Server[Any]) -> AsyncIterator[dict[str, Any]]:
        if args.mode == "init-delay":
            await asyncio.sleep(args.delay)
        try:
            yield {}
        finally:
            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)

    server = Server("mcp-stdio-fixture", version="1.0.0", lifespan=lifespan)
    generation = 0

    def selected_schema(name: str) -> dict[str, Any]:
        if name == "env-secret":
            return {
                "type": "object",
                "description": os.environ.get("MCP_FIXTURE_SCHEMA_SECRET", "<missing>"),
            }
        return SCHEMAS[name]

    input_schema = selected_schema(args.schema)
    output_schema = None if args.output_schema == "none" else selected_schema(args.output_schema)
    description = (
        os.environ.get(args.description_env, "<missing>")
        if args.description_env is not None
        else os.environ.get("MCP_FIXTURE_DESCRIPTION", "Return the supplied message.")
    )
    echo = _tool(
        os.environ.get("MCP_FIXTURE_TOOL_NAME", "echo"),
        description,
        input_schema,
        output_schema,
    )
    upper = _tool(
        "upper",
        "Return the supplied message in uppercase.",
        SCHEMAS["valid"],
        output_schema,
    )
    refreshed = _tool(
        "refreshed",
        "Tool added after a list-changed notification.",
        SCHEMAS["valid"],
        output_schema,
    )

    async def notify_list_changed() -> None:
        await asyncio.sleep(args.notify_delay)
        await server.request_context.session.send_tool_list_changed()

    async def crash_after_delay() -> None:
        await asyncio.sleep(args.notify_delay)
        os._exit(18)

    async def send_invalid_notification() -> None:
        await asyncio.sleep(args.notify_delay)
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/fixture-invalid",
            "params": {"data": os.environ.get("MCP_FIXTURE_NOISE", "fixture-noise")},
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        os.write(sys.stdout.fileno(), line.encode("utf-8"))

    async def send_malformed_after_list() -> None:
        nonlocal child_process
        await asyncio.sleep(args.notify_delay)
        child_process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        os.write(
            sys.stdout.fileno(),
            (os.environ.get("MCP_FIXTURE_NOISE", "not-json-delayed") + "\n").encode("utf-8"),
        )


    async def list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
        nonlocal generation
        cursor = request.params.cursor if request.params is not None else None
        if args.mode == "pagination":
            return (
                types.ListToolsResult(tools=[echo], nextCursor="page-2")
                if cursor is None
                else types.ListToolsResult(tools=[upper])
            )
        if args.mode == "repeat-cursor":
            tools = [echo] if cursor is None else [upper]
            return types.ListToolsResult(tools=tools, nextCursor="loop")
        if args.mode == "unique-cursor":
            page = int(cursor) if cursor is not None else 0
            tool = _tool(
                f"cursor-{page}",
                "Unique cursor page.",
                SCHEMAS["valid"],
                output_schema,
            )
            return types.ListToolsResult(tools=[tool], nextCursor=str(page + 1))
        if args.mode == "large-page":
            tools = [
                _tool(
                    f"large-{index}",
                    "Large single-page catalog.",
                    SCHEMAS["valid"],
                    output_schema,
                )
                for index in range(257)
            ]
            return types.ListToolsResult(tools=tools)
        if args.mode == "duplicate-tools":
            duplicate = _tool(
                echo.name,
                "Second tool with the same remote name.",
                SCHEMAS["valid-local-ref"],
                output_schema,
            )
            return types.ListToolsResult(tools=[echo, duplicate])
        if args.mode in {"list-changed", "list-changed-crash", "list-changed-unsafe"}:
            if generation == 0:
                generation = 1
                background_tasks.add(asyncio.create_task(notify_list_changed()))
                return types.ListToolsResult(tools=[echo])
            if args.mode == "list-changed-crash":
                os._exit(18)
            if args.mode == "list-changed-unsafe":
                unsafe = _tool(
                    "unsafe",
                    "Tool with an unsafe refreshed schema.",
                    SCHEMAS["external-ref"],
                    output_schema,
                )
                return types.ListToolsResult(tools=[echo, unsafe])
            return types.ListToolsResult(tools=[echo, refreshed])
        if args.mode == "idle-crash" and generation == 0:
            generation = 1
            background_tasks.add(asyncio.create_task(crash_after_delay()))
        if args.mode == "invalid-notification" and generation == 0:
            generation = 1
            background_tasks.add(asyncio.create_task(send_invalid_notification()))
        if args.mode == "malformed-after-list" and generation == 0:
            generation = 1
            background_tasks.add(asyncio.create_task(send_malformed_after_list()))
        return types.ListToolsResult(tools=[echo])

    if args.mode != "no-tools":
        server.list_tools()(list_tools)

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        message = str(arguments.get("message", ""))
        if args.call_file is not None:
            with args.call_file.open("a", encoding="utf-8") as calls:
                calls.write(f"{os.getpid()}:{name}:{message}\n")
        if args.mode == "call-delay":
            await asyncio.sleep(args.delay)
        if args.mode == "call-crash":
            os._exit(19)
        if args.mode == "call-results":
            if message == "tool-error":
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="business failure")],
                    isError=True,
                )
            if message == "invalid-output":
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="invalid output")],
                    structuredContent={"message": 42},
                )
            if message == "rich":
                return types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text="rich text",
                            _meta={"private": "discard-me"},
                        ),
                        types.ImageContent(
                            type="image",
                            data="YWJj",
                            mimeType="image/png",
                            _meta={"private": "discard-me"},
                        ),
                        types.AudioContent(
                            type="audio",
                            data="MTI=",
                            mimeType="audio/wav",
                        ),
                        types.ResourceLink(
                            type="resource_link",
                            name="fixture-link",
                            uri="file:///fixture-link.txt",
                            description="fixture metadata",
                            mimeType="text/plain",
                            size=7,
                            _meta={"private": "discard-me"},
                        ),
                        types.EmbeddedResource(
                            type="resource",
                            resource=types.TextResourceContents(
                                uri="file:///fixture.txt",
                                mimeType="text/plain",
                                text="embedded text",
                                _meta={"private": "discard-me"},
                            ),
                        ),
                        types.EmbeddedResource(
                            type="resource",
                            resource=types.BlobResourceContents(
                                uri="file:///fixture.bin",
                                mimeType="application/octet-stream",
                                blob="YmxvYg==",
                                _meta={"private": "discard-me"},
                            ),
                        ),
                    ],
                    structuredContent={"message": "rich", "nested": {"value": message}},
                    _meta={"private": "discard-me"},
                )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=message)],
                structuredContent={"message": message},
            )
        if name == echo.name or name == "refreshed":
            if output_schema is not None:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=message)],
                    structuredContent={"message": message},
                )
            return [types.TextContent(type="text", text=message)]
        if name == "upper":
            return [types.TextContent(type="text", text=message.upper())]
        raise ValueError(f"unknown tool: {name}")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(
                    tools_changed=args.mode
                    in {"list-changed", "list-changed-crash", "list-changed-unsafe"}
                )
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_arguments())))
