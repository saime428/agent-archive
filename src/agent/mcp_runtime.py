from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

from agent.mcp_config import McpConfigStore, McpRuntimeError, McpServerConfig, load_mcp_server_configs

McpCallStatus = Literal["ok", "tool_error", "timeout", "failed"]

_SERVER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_DISCOVERY_TIMEOUT_SECONDS = 15.0
_CALL_TIMEOUT_SECONDS = 30.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_MAX_TOOL_SCHEMA_BYTES = 64 * 1024
_MAX_DISCOVERY_PAGES = 64
_MAX_TOOLS_PER_SERVER = 256
# ponytail: regex schemas stay disabled until validation has a hard, interruptible CPU budget.
_UNSAFE_SCHEMA_KEYWORDS = {"pattern", "patternProperties"}
_SCHEMA_MAP_KEYWORDS = {"$defs", "definitions", "dependentSchemas", "properties", "patternProperties"}
_SCHEMA_ARRAY_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SCHEMA_SINGLE_KEYWORDS = {
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
}
_SUPPORTED_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_REDACTION_MARKER = "[REDACTED]"
_MCP_LOGGERS = ("mcp.client.stdio", "client.stdio.win32")
_MAX_CALL_SUMMARY_CHARS = 4 * 1024
_MAX_CALL_DIAGNOSTIC_BYTES = 4 * 1024
_MAX_CALL_DATA_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True, eq=False)
class McpToolTarget:
    server_id: str
    remote_name: str
    snapshot_contract: object


@dataclass(frozen=True, slots=True, eq=False)
class McpToolDefinition:
    exposed_name: str
    target: McpToolTarget
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    input_validator: object


@dataclass(frozen=True, slots=True)
class McpCallResult:
    status: McpCallStatus
    summary: str
    data: dict[str, Any] | None = None
    diagnostic_details: dict[str, Any] | None = None
    redaction_replacements: int = 0


def build_mcp_tool_name(server_id: str, remote_name: str) -> str:
    if not isinstance(server_id, str) or _SERVER_ID_PATTERN.fullmatch(server_id) is None:
        raise ValueError("MCP server ID must contain only ASCII letters, digits, '_' or '-'.")
    if not isinstance(remote_name, str) or not remote_name:
        raise ValueError("MCP remote tool name must be a non-empty string.")
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", remote_name)
    candidate = f"mcp__{server_id}__{normalized}"
    if len(candidate) <= 64:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
    return f"{candidate[:55]}_{digest}"


def _environment_value(environ: Mapping[str, str], name: str) -> str | None:
    if os.name != "nt":
        return environ.get(name)
    folded_name = name.casefold()
    return next((value for key, value in environ.items() if key.casefold() == folded_name), None)


def _comparison_path(path: Path) -> str:
    value = os.path.normcase(os.path.normpath(str(path)))
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\unc\\"):
        return f"\\\\{value[8:]}"
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value
@dataclass(frozen=True, slots=True)
class _SecretValues:
    values: tuple[str, ...]
    pattern: re.Pattern[str] | None

    @classmethod
    def from_values(cls, values: list[str]) -> _SecretValues:
        unique = tuple(sorted({value for value in values if value}, key=lambda item: (-len(item), item)))
        pattern = re.compile("|".join(re.escape(value) for value in unique)) if unique else None
        return cls(values=unique, pattern=pattern)

    def contains(self, value: str) -> bool:
        return self.pattern is not None and self.pattern.search(value) is not None

    def redact(self, value: str) -> str:
        return value if self.pattern is None else self.pattern.sub(_REDACTION_MARKER, value)

    def redact_with_count(self, value: str) -> tuple[str, int]:
        if self.pattern is None:
            return value, 0
        return self.pattern.subn(_REDACTION_MARKER, value)


@dataclass(frozen=True, slots=True)
class _SnapshotContract:
    output_validator: object | None


@dataclass(frozen=True, slots=True)
class _ServerStart:
    config: McpServerConfig
    environment: tuple[tuple[str, str], ...]
    secrets: _SecretValues


@dataclass(slots=True)
class _OwnerCommand:
    kind: Literal["discover", "call", "close"]
    future: concurrent.futures.Future[Any]
    initial: bool = False
    target: McpToolTarget | None = None
    arguments: dict[str, Any] | None = None
    state: Literal["queued", "running", "canceled", "finished"] = "queued"
    state_lock: threading.Lock = dataclass_field(default_factory=threading.Lock)

    def try_start(self) -> bool:
        with self.state_lock:
            if self.state != "queued":
                return False
            self.state = "running"
            return True

    def cancel_if_queued(self) -> bool:
        with self.state_lock:
            if self.state != "queued":
                return False
            self.state = "canceled"
            return True

    def finish(self) -> None:
        with self.state_lock:
            if self.state == "running":
                self.state = "finished"


class _SnapshotSafetyError(RuntimeError):
    def __init__(self, *, server_id: str, message: str) -> None:
        self.server_id = server_id
        self.safe_message = message
        super().__init__(message)


class _McpProtocolError(RuntimeError):
    pass


class _McpLogFilter(logging.Filter):
    def __init__(self, *, owner_thread_id: int, package_root: Path) -> None:
        super().__init__()
        self._owner_thread_id = owner_thread_id
        self._package_root = _comparison_path(package_root)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.thread != self._owner_thread_id:
            return True
        try:
            pathname = _comparison_path(Path(record.pathname).resolve())
            from_sdk = os.path.commonpath((pathname, self._package_root)) == self._package_root
        except (OSError, RuntimeError, ValueError):
            from_sdk = False
        if record.name not in _MCP_LOGGERS and not from_sdk:
            return True
        record.msg = "MCP protocol diagnostic suppressed"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return False


def _prepare_server_starts(
    configs: tuple[McpServerConfig, ...],
    environ: Mapping[str, str],
) -> tuple[_ServerStart, ...]:
    prepared = []
    all_secret_values = []
    for config in configs:
        environment: dict[str, str] = {}
        for name in config.pass_env:
            value = _environment_value(environ, name)
            if value is None:
                raise McpRuntimeError(
                    stage="initialize",
                    server_id=config.server_id,
                    message=f"Required environment variable {name!r} is not set.",
                )
            environment[name] = value
            all_secret_values.append(value)
        environment["PATH"] = config.subprocess_path
        if config.subprocess_pathext is not None:
            environment["PATHEXT"] = config.subprocess_pathext
        prepared.append((config, tuple(environment.items())))

    secrets = _SecretValues.from_values(all_secret_values)
    return tuple(
        _ServerStart(
            config=config,
            environment=environment,
            secrets=secrets,
        )
        for config, environment in prepared
    )


def _build_schema_registry(
    schema: dict[str, Any],
    *,
    server_id: str,
    field: str,
) -> object:
    from referencing import Registry
    from referencing.exceptions import Unresolvable
    from referencing.jsonschema import DRAFT202012

    root_uri = "https://agent.invalid/mcp-schema"
    registry = Registry().with_resource(root_uri, DRAFT202012.create_resource(schema)).crawl()
    references: list[tuple[str, str]] = []
    stack: list[tuple[Any, str, str]] = [(schema, root_uri, "schema")]
    while stack:
        value, base_uri, context = stack.pop()
        if isinstance(value, dict):
            schema_id = value.get("$id") if context == "schema" else None
            local_base = urljoin(base_uri, schema_id) if isinstance(schema_id, str) else base_uri
            for key, child in value.items():
                if context == "schema" and key in {"$ref", "$dynamicRef"} and isinstance(child, str):
                    references.append((local_base, child))
                if context == "schema":
                    if key in _SCHEMA_MAP_KEYWORDS:
                        child_context = "schema_map"
                    elif key in _SCHEMA_ARRAY_KEYWORDS:
                        child_context = "schema_list"
                    elif key in _SCHEMA_SINGLE_KEYWORDS:
                        child_context = "schema"
                    else:
                        continue
                elif context == "schema_map":
                    child_context = "schema"
                else:
                    continue
                if isinstance(child, (dict, list)):
                    stack.append((child, local_base, child_context))
        elif isinstance(value, list) and context == "schema_list":
            stack.extend(
                (child, base_uri, "schema")
                for child in value
                if isinstance(child, (dict, list))
            )

    try:
        for base_uri, reference in references:
            registry.resolver(base_uri).lookup(reference)
    except Unresolvable:
        raise _SnapshotSafetyError(
            server_id=server_id,
            message=f"A tool {field} contains an unresolved fragment reference.",
        ) from None
    return registry



def _freeze_tool_schemas(
    input_schema: Any,
    output_schema: Any,
    *,
    server_id: str,
    secrets: _SecretValues,
) -> tuple[dict[str, Any], dict[str, Any] | None, object, object | None]:
    input_public, input_bytes = _normalize_schema(
        input_schema,
        field="inputSchema",
        server_id=server_id,
        secrets=secrets,
    )
    output_public: dict[str, Any] | None = None
    output_bytes = b""
    if output_schema is not None:
        output_public, output_bytes = _normalize_schema(
            output_schema,
            field="outputSchema",
            server_id=server_id,
            secrets=secrets,
        )
    if len(input_bytes) + len(output_bytes) > _MAX_TOOL_SCHEMA_BYTES:
        raise _SnapshotSafetyError(
            server_id=server_id,
            message="A tool input/output schema exceeds the 64 KiB safety limit.",
        )

    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    def compile_schema(schema_bytes: bytes, field: str) -> object:
        schema = json.loads(schema_bytes)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise _SnapshotSafetyError(
                server_id=server_id,
                message=f"A tool {field} is not valid JSON Schema 2020-12.",
            ) from None
        registry = _build_schema_registry(schema, server_id=server_id, field=field)
        return Draft202012Validator(schema, registry=registry)

    input_validator = compile_schema(input_bytes, "inputSchema")
    output_validator = compile_schema(output_bytes, "outputSchema") if output_public is not None else None
    return input_public, output_public, input_validator, output_validator


def _normalize_schema(
    schema: Any,
    *,
    field: str,
    server_id: str,
    secrets: _SecretValues,
) -> tuple[dict[str, Any], bytes]:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise _SnapshotSafetyError(
            server_id=server_id,
            message=f"A tool {field} must have an object root.",
        )

    rough_size = 0

    def add_size(amount: int) -> None:
        nonlocal rough_size
        rough_size += amount
        if rough_size > _MAX_TOOL_SCHEMA_BYTES:
            raise _SnapshotSafetyError(
                server_id=server_id,
                message=f"A tool {field} exceeds the 64 KiB safety limit.",
            )

    stack: list[tuple[Any, str]] = [(schema, "schema")]
    while stack:
        value, context = stack.pop()
        if isinstance(value, dict):
            add_size(2 if not value else len(value) + 1)
            for key, child in value.items():
                if not isinstance(key, str):
                    raise _SnapshotSafetyError(
                        server_id=server_id,
                        message=f"A tool {field} contains a non-string key.",
                    )
                add_size(len(key) + 3)
                if secrets.contains(key):
                    raise _SnapshotSafetyError(
                        server_id=server_id,
                        message=f"A tool {field} contains a protected environment value.",
                    )
                if context == "schema":
                    if key in _UNSAFE_SCHEMA_KEYWORDS:
                        raise _SnapshotSafetyError(
                            server_id=server_id,
                            message=f"A tool {field} uses unsupported regular-expression validation.",
                        )
                    if key == "$schema" and child != _SUPPORTED_SCHEMA_DIALECT:
                        raise _SnapshotSafetyError(
                            server_id=server_id,
                            message=f"A tool {field} uses an unsupported JSON Schema dialect.",
                        )
                    if key in {"$ref", "$dynamicRef"} and (
                        not isinstance(child, str) or not child.startswith("#")
                    ):
                        raise _SnapshotSafetyError(
                            server_id=server_id,
                            message=f"A tool {field} contains a non-fragment reference.",
                        )
                    if key in _SCHEMA_MAP_KEYWORDS:
                        child_context = "schema_map"
                    elif key in _SCHEMA_ARRAY_KEYWORDS:
                        child_context = "schema_list"
                    elif key in _SCHEMA_SINGLE_KEYWORDS:
                        child_context = "schema"
                    else:
                        child_context = "other"
                elif context == "schema_map":
                    child_context = "schema"
                else:
                    child_context = "other"
                stack.append((child, child_context))
        elif isinstance(value, list):
            add_size(2 if not value else len(value) + 1)
            child_context = "schema" if context == "schema_list" else "other"
            stack.extend((child, child_context) for child in value)
        elif isinstance(value, str):
            add_size(len(value) + 2)
            if secrets.contains(value):
                raise _SnapshotSafetyError(
                    server_id=server_id,
                    message=f"A tool {field} contains a protected environment value.",
                )
        else:
            add_size(1)

    try:
        encoded = json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_TOOL_SCHEMA_BYTES:
            raise _SnapshotSafetyError(
                server_id=server_id,
                message=f"A tool {field} exceeds the 64 KiB safety limit.",
            )
        public = json.loads(encoded)

    except (RecursionError, TypeError, ValueError):
        raise _SnapshotSafetyError(
            server_id=server_id,
            message=f"A tool {field} is not bounded JSON data.",
        ) from None
    if secrets.contains(encoded.decode("utf-8")):
        raise _SnapshotSafetyError(
            server_id=server_id,
            message=f"A tool {field} contains a protected environment value.",
        )
    return public, encoded


def _definitions_from_tools(
    server_id: str,
    tools: list[Any],
    secrets: _SecretValues,
) -> tuple[McpToolDefinition, ...]:
    definitions = []
    for tool in tools:
        remote_name = tool.name
        if not isinstance(remote_name, str) or not remote_name or secrets.contains(remote_name):
            raise _SnapshotSafetyError(
                server_id=server_id,
                message="A tool name is invalid or contains a protected environment value.",
            )
        input_schema, output_schema, input_validator, output_validator = _freeze_tool_schemas(
            tool.inputSchema,
            tool.outputSchema,
            server_id=server_id,
            secrets=secrets,
        )
        try:
            exposed_name = build_mcp_tool_name(server_id, remote_name)
        except ValueError:
            raise _SnapshotSafetyError(server_id=server_id, message="A tool name is invalid.") from None
        target = McpToolTarget(
            server_id=server_id,
            remote_name=remote_name,
            snapshot_contract=_SnapshotContract(output_validator=output_validator),
        )
        definitions.append(
            McpToolDefinition(
                exposed_name=exposed_name,
                target=target,
                description=secrets.redact(tool.description or ""),
                input_schema=input_schema,
                output_schema=output_schema,
                input_validator=input_validator,
            )
        )
    return tuple(definitions)


def _runtime_error_copy(error: McpRuntimeError) -> McpRuntimeError:
    return McpRuntimeError(stage=error.stage, server_id=error.server_id, message=error.message)


def _set_future_result(future: concurrent.futures.Future[Any], value: Any) -> None:
    if not future.done():
        future.set_result(value)


def _set_future_exception(future: concurrent.futures.Future[Any], error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)


def _session_ended_error(server_id: str) -> McpRuntimeError:
    return McpRuntimeError(
        stage="discovery",
        server_id=server_id,
        message="The MCP server session ended unexpectedly.",
    )



def _transport_cleanup_error() -> McpRuntimeError:
    return McpRuntimeError(
        stage="runtime",
        server_id=None,
        message="The MCP runtime transport did not stop in time.",
    )


@dataclass(frozen=True, slots=True)
class _OwnerCallOutcome:
    result: McpCallResult
    poison_server: bool = False


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "?[truncated]"
    return value[: max(0, limit - len(marker))] + marker


def _redact_call_value(
    value: Any,
    secrets: _SecretValues,
    *,
    depth: int = 0,
) -> tuple[Any, int]:
    if depth >= 12:
        return {"omitted": True, "reason": "maximum depth exceeded"}, 0
    if isinstance(value, str):
        redacted, count = secrets.redact_with_count(value)
        return _bounded_text(redacted, 32 * 1024), count
    if value is None or isinstance(value, (bool, int)):
        return value, 0
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None, 0
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        replacements = 0
        for index, (raw_key, child) in enumerate(value.items()):
            if index >= 256:
                normalized["_omitted"] = {"reason": "item limit exceeded"}
                break
            key, key_count = secrets.redact_with_count(str(raw_key))
            replacements += key_count
            public_key = _bounded_text(key, 512)
            if public_key in normalized:
                public_key = f"{public_key}#{index}"
            public_child, child_count = _redact_call_value(child, secrets, depth=depth + 1)
            replacements += child_count
            normalized[public_key] = public_child
        return normalized, replacements
    if isinstance(value, (list, tuple)):
        normalized_list = []
        replacements = 0
        for child in value[:256]:
            public_child, child_count = _redact_call_value(child, secrets, depth=depth + 1)
            normalized_list.append(public_child)
            replacements += child_count
        if len(value) > 256:
            normalized_list.append({"omitted": True, "reason": "item limit exceeded"})
        return normalized_list, replacements
    redacted, count = secrets.redact_with_count(str(value))
    return _bounded_text(redacted, 1024), count


def _bounded_call_data(data: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError):
        return {"omitted": True, "reason": "result is not bounded JSON data"}
    if len(encoded) <= _MAX_CALL_DATA_BYTES:
        return data
    return {
        "omitted": True,
        "reason": "result exceeded the 128 KiB safety limit",
        "size": len(encoded),
    }


def _bounded_diagnostic(details: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            details,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError):
        return {"stage": "normalization"}
    if len(encoded) <= _MAX_CALL_DIAGNOSTIC_BYTES:
        return details
    return {"stage": str(details.get("stage", "call")), "truncated": True}


def _base64_payload_size(value: str) -> int:
    stripped = value.rstrip("=")
    return max(0, (len(stripped) * 3) // 4)


def _resource_metadata(resource: Any, *, include_text: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "uri": str(getattr(resource, "uri", "")),
        "mime_type": getattr(resource, "mimeType", None),
    }
    if include_text:
        data["text"] = getattr(resource, "text", "")
    else:
        blob = getattr(resource, "blob", "")
        data.update({"size": _base64_payload_size(blob), "omitted": True})
    return data


def _normalize_content_block(block: Any) -> tuple[dict[str, Any], str | None]:
    block_type = getattr(block, "type", None)
    if block_type == "text":
        text = str(getattr(block, "text", ""))
        return {"type": "text", "text": text}, text
    if block_type in {"image", "audio"}:
        encoded = str(getattr(block, "data", ""))
        return {
            "type": block_type,
            "mime_type": getattr(block, "mimeType", None),
            "size": _base64_payload_size(encoded),
            "omitted": True,
        }, None
    if block_type == "resource_link":
        return {
            "type": "resource_link",
            "name": getattr(block, "name", ""),
            "title": getattr(block, "title", None),
            "uri": str(getattr(block, "uri", "")),
            "description": getattr(block, "description", None),
            "mime_type": getattr(block, "mimeType", None),
            "size": getattr(block, "size", None),
        }, None
    if block_type == "resource":
        resource = getattr(block, "resource", None)
        if resource is None:
            return {"type": "resource", "omitted": True}, None
        is_text = hasattr(resource, "text")
        return {
            "type": "resource",
            "resource": _resource_metadata(resource, include_text=is_text),
        }, getattr(resource, "text", None) if is_text else None
    return {"type": "unknown", "omitted": True}, None


def _output_validation_diagnostic(error: Any, secrets: _SecretValues) -> tuple[dict[str, Any], int]:
    path = "$"
    for segment in getattr(error, "absolute_path", ()):
        path += f"[{segment}]" if isinstance(segment, int) else f".{segment}"
    redacted_path, replacements = secrets.redact_with_count(path)
    return _bounded_diagnostic(
        {
            "stage": "output_validation",
            "path": _bounded_text(redacted_path, 1024),
            "validator": _bounded_text(str(getattr(error, "validator", "unknown")), 128),
        }
    ), replacements


def _normalize_call_result(
    raw_result: Any,
    target: McpToolTarget,
    secrets: _SecretValues,
) -> _OwnerCallOutcome:
    contract = target.snapshot_contract
    output_validator = (
        contract.output_validator if isinstance(contract, _SnapshotContract) else None
    )
    if not bool(getattr(raw_result, "isError", False)) and output_validator is not None:
        structured = getattr(raw_result, "structuredContent", None)
        if structured is None:
            return _OwnerCallOutcome(
                McpCallResult(
                    status="failed",
                    summary="MCP tool output validation failed.",
                    diagnostic_details={
                        "stage": "output_validation",
                        "path": "$",
                        "validator": "required",
                    },
                ),
                poison_server=True,
            )
        error = next(iter(output_validator.iter_errors(structured)), None)
        if error is not None:
            diagnostic, replacements = _output_validation_diagnostic(error, secrets)
            return _OwnerCallOutcome(
                McpCallResult(
                    status="failed",
                    summary="MCP tool output validation failed.",
                    diagnostic_details=diagnostic,
                    redaction_replacements=replacements,
                ),
                poison_server=True,
            )

    content = []
    summary_parts = []
    for block in list(getattr(raw_result, "content", ()))[:256]:
        normalized, summary_text = _normalize_content_block(block)
        content.append(normalized)
        if summary_text:
            summary_parts.append(summary_text)
    raw_data: dict[str, Any] = {"content": content}
    structured = getattr(raw_result, "structuredContent", None)
    if structured is not None:
        raw_data["structured_content"] = structured

    public_data, replacements = _redact_call_value(raw_data, secrets)
    assert isinstance(public_data, dict)
    data = _bounded_call_data(public_data)
    summary_source = "\n".join(summary_parts) or (
        "MCP tool returned an error."
        if bool(getattr(raw_result, "isError", False))
        else "MCP tool completed."
    )
    summary, summary_replacements = secrets.redact_with_count(summary_source)
    replacements += summary_replacements
    status: McpCallStatus = "tool_error" if bool(getattr(raw_result, "isError", False)) else "ok"
    return _OwnerCallOutcome(
        McpCallResult(
            status=status,
            summary=_bounded_text(summary, _MAX_CALL_SUMMARY_CHARS),
            data=data,
            redaction_replacements=replacements,
        )
    )


def _call_failure_result(
    *,
    status: Literal["timeout", "failed"],
    summary: str,
    stage: str,
    secrets: _SecretValues | None = None,
    error: BaseException | None = None,
) -> McpCallResult:
    replacements = 0
    if secrets is not None and error is not None:
        _, replacements = secrets.redact_with_count(str(error))
    return McpCallResult(
        status=status,
        summary=summary,
        diagnostic_details={"stage": stage},
        redaction_replacements=replacements,
    )


class McpStdioRuntime:
    def __init__(
        self,
        workspace: Path,
        *,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._workspace = Path(workspace)
        self._home = Path(home) if home is not None else None
        self._environ = dict(environ) if environ is not None else None
        self._condition = threading.Condition()
        self._state: Literal["new", "starting", "ready", "failed", "closing", "closed"] = "new"
        self._failure: McpRuntimeError | None = None
        self._snapshot: tuple[McpToolDefinition, ...] = ()
        self._server_snapshots: dict[str, tuple[McpToolDefinition, ...]] = {}
        self._known_targets: set[McpToolTarget] = set()
        self._configs: tuple[McpServerConfig, ...] = ()
        self._starts: dict[str, _ServerStart] = {}
        self._dirty_generation: dict[str, int] = {}
        self._published_generation: dict[str, int] = {}
        self._refreshing = False
        self._refresh_error: McpRuntimeError | None = None

        self._transport_lock = threading.Lock()
        self._transport_closing = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: dict[str, asyncio.Queue[_OwnerCommand]] = {}
        self._owners: dict[str, asyncio.Task[None]] = {}
        self._dead_servers: set[str] = set()
        self._stop_event: asyncio.Event | None = None
        self._loop_ready = threading.Event()
        self._loop_finished = threading.Event()
        self._loop_failure: McpRuntimeError | None = None

    def discover_tools(self) -> tuple[McpToolDefinition, ...]:
        initial = False
        owns_discovery = False
        captured: dict[str, int] = {}
        try:
            with self._condition:
                while True:
                    if self._state in {"closing", "closed"}:
                        raise self._closed_error()
                    if self._state == "failed":
                        assert self._failure is not None
                        raise _runtime_error_copy(self._failure)
                    if self._state == "new":
                        self._state = "starting"
                        initial = True
                        owns_discovery = True
                        break
                    if self._state == "starting" or self._refreshing:
                        self._condition.wait()
                        continue

                    captured = {
                        config.server_id: self._dirty_generation.get(config.server_id, 0)
                        for config in self._configs
                        if config.server_id not in self._dead_servers
                        and self._dirty_generation.get(config.server_id, 0)
                        > self._published_generation.get(config.server_id, 0)
                    }
                    if captured and self._refresh_error is not None:
                        captured = {
                            config.server_id: self._dirty_generation.get(config.server_id, 0)
                            for config in self._configs
                            if config.server_id not in self._dead_servers
                        }
                    if captured:
                        self._refreshing = True
                        owns_discovery = True
                        break
                    if self._refresh_error is not None:
                        raise _runtime_error_copy(self._refresh_error)
                    return self._snapshot

            return self._initial_discovery() if initial else self._refresh_discovery(captured)
        except McpRuntimeError:
            raise
        except BaseException:
            if owns_discovery:
                self._abort_discovery()
            raise

    def call_tool(
        self,
        target: McpToolTarget,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> McpCallResult:
        timeout = _CALL_TIMEOUT_SECONDS if timeout_seconds is None else max(0.0, timeout_seconds)
        with self._condition:
            start = self._starts.get(getattr(target, "server_id", ""))
            if (
                self._state != "ready"
                or target not in self._known_targets
                or start is None
                or target.server_id in self._dead_servers
            ):
                return _call_failure_result(
                    status="failed",
                    summary="MCP tool target is not available.",
                    stage="routing",
                )

        try:
            encoded_arguments = json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            public_arguments = json.loads(encoded_arguments)
        except (RecursionError, TypeError, ValueError):
            return _call_failure_result(
                status="failed",
                summary="MCP tool arguments are not valid JSON.",
                stage="arguments",
            )
        if not isinstance(public_arguments, dict):
            return _call_failure_result(
                status="failed",
                summary="MCP tool arguments must be an object.",
                stage="arguments",
            )

        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        command = _OwnerCommand(
            kind="call",
            future=future,
            target=target,
            arguments=public_arguments,
        )
        self._enqueue(target.server_id, command)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if command.cancel_if_queued():
                result = _call_failure_result(
                    status="timeout",
                    summary="MCP tool call timed out before it started.",
                    stage="queue_timeout",
                )
                _set_future_result(future, result)
                return result
            if future.done():
                try:
                    completed = future.result()
                except BaseException as exc:
                    return _call_failure_result(
                        status="failed",
                        summary="MCP tool call failed.",
                        stage="request",
                        secrets=start.secrets,
                        error=exc,
                    )
                return completed
            result = _call_failure_result(
                status="timeout",
                summary="MCP tool call timed out after the request started.",
                stage="request_timeout",
            )
            self._fail_running_call(target.server_id)
            return result
        except BaseException as exc:
            return _call_failure_result(
                status="failed",
                summary="MCP tool call failed.",
                stage="request",
                secrets=start.secrets,
                error=exc,
            )
        return result

    def _fail_running_call(self, server_id: str) -> None:
        self._isolate_server(server_id)

    def _retire_server_locked(self, server_id: str) -> None:
        self._dead_servers.add(server_id)
        self._server_snapshots.pop(server_id, None)
        self._snapshot = self._combine_snapshots(self._server_snapshots)
        self._known_targets = {
            target for target in self._known_targets if target.server_id != server_id
        }
        self._dirty_generation.pop(server_id, None)
        self._published_generation.pop(server_id, None)
        if self._refresh_error is not None and self._refresh_error.server_id == server_id:
            self._refresh_error = None

    def _cancel_server(self, server_id: str) -> bool:
        loop = self._loop
        if loop is None:
            return True
        finished = threading.Event()

        def cancel() -> None:
            owner = self._owners.get(server_id)
            if owner is None or owner.done():
                finished.set()
                return
            owner.add_done_callback(lambda _task: finished.set())
            owner.cancel()

        try:
            loop.call_soon_threadsafe(cancel)
        except RuntimeError:
            return False
        return finished.wait(_CLOSE_TIMEOUT_SECONDS)

    def _isolate_server(self, server_id: str) -> bool:
        with self._condition:
            if self._state != "ready":
                return False
            self._retire_server_locked(server_id)
            self._condition.notify_all()
        if self._cancel_server(server_id):
            return True

        error = _transport_cleanup_error()
        with self._condition:
            if self._state == "ready":
                self._state = "failed"
                self._failure = error
                self._refreshing = False
                self._condition.notify_all()
        try:
            self._close_transport()
        except McpRuntimeError:
            pass
        return False

    def _abort_discovery(self) -> None:
        error = McpRuntimeError(
            stage="discovery",
            server_id=None,
            message="MCP discovery was interrupted.",
        )
        with self._condition:
            if self._state in {"starting", "ready"}:
                self._state = "failed"
                self._failure = error
            self._refreshing = False
            self._condition.notify_all()
        self._request_transport_stop()
        try:
            self._close_transport()
        except McpRuntimeError:
            pass


    def _finish_close_locked(self) -> None:
        self._state = "closed"
        self._failure = None
        self._snapshot = ()
        self._server_snapshots.clear()
        self._known_targets.clear()
        self._configs = ()
        self._starts.clear()
        self._dirty_generation.clear()
        self._published_generation.clear()
        self._refreshing = False
        self._refresh_error = None
        self._environ = None
        self._loop = None
        self._queues.clear()
        self._owners.clear()
        self._dead_servers.clear()
        self._stop_event = None
        self._thread = None
        self._loop_failure = None
        self._condition.notify_all()


    def close(self) -> None:
        with self._condition:
            if self._state == "closed":
                return
            if self._state == "closing":
                while self._state == "closing":
                    self._condition.wait()
                if self._state == "closed":
                    return
            self._state = "closing"
            self._condition.notify_all()

        try:
            self._close_transport()
        except BaseException:
            stopped = self._transport_stopped()
            with self._condition:
                if stopped:
                    self._finish_close_locked()
                else:
                    self._state = "failed"
                    self._failure = _transport_cleanup_error()
                    self._refreshing = False
                    self._condition.notify_all()
            raise
        else:
            with self._condition:
                self._finish_close_locked()

    def _initial_discovery(self) -> tuple[McpToolDefinition, ...]:
        try:
            environment = self._environ if self._environ is not None else dict(os.environ)
            configs = McpConfigStore(
                self._workspace,
                home=self._home,
                environ=self._environ,
            ).load_enabled_configs()
            starts = _prepare_server_starts(configs, environment)
            with self._condition:
                if self._state != "starting":
                    raise self._closed_error()
                self._configs = configs
                self._starts = {start.config.server_id: start for start in starts}
                self._dirty_generation = {config.server_id: 0 for config in configs}
                self._published_generation = {config.server_id: 0 for config in configs}
            if starts:
                if not self._start_loop(starts):
                    raise self._closed_error()
                discovered = self._dispatch_discovery(tuple(self._starts), initial=True)
            else:
                discovered = {}
        except _SnapshotSafetyError as exc:
            error = McpRuntimeError(
                stage="discovery",
                server_id=exc.server_id,
                message=exc.safe_message,
            )
            return self._fail_initial(error)
        except McpRuntimeError as exc:
            return self._fail_initial(exc)
        except Exception:
            error = McpRuntimeError(
                stage="initialize",
                server_id=None,
                message="The MCP runtime could not be initialized.",
            )
            return self._fail_initial(error)

        snapshots = {server_id: discovered[server_id] for server_id in discovered}
        snapshot = self._combine_snapshots(snapshots)
        dead_server: str | None = None
        with self._condition:
            if self._state != "starting":
                publish = False
            elif dead_server := self._ended_server_locked():
                publish = False
            else:
                self._server_snapshots = snapshots
                self._snapshot = snapshot
                self._known_targets.update(definition.target for definition in snapshot)
                self._state = "ready"
                self._condition.notify_all()
                publish = True
        if dead_server is not None:
            return self._fail_initial(
                _session_ended_error(dead_server)
            )
        if not publish:
            self._close_transport()
            raise self._closed_error()
        return snapshot

    def _fail_initial(self, error: McpRuntimeError) -> tuple[McpToolDefinition, ...]:
        with self._condition:
            if self._state == "starting":
                self._state = "failed"
                self._failure = _runtime_error_copy(error)
                final_error = error
            else:
                final_error = self._closed_error()
            self._condition.notify_all()
        self._close_transport()
        raise _runtime_error_copy(final_error)

    def _refresh_discovery(self, captured: dict[str, int]) -> tuple[McpToolDefinition, ...]:
        try:
            discovered = self._dispatch_discovery(tuple(captured), initial=False)
        except _SnapshotSafetyError as exc:
            error = McpRuntimeError(
                stage="discovery",
                server_id=exc.server_id,
                message=exc.safe_message,
            )
            close_transport = False
            final_snapshot: tuple[McpToolDefinition, ...] | None = None
            final_error: McpRuntimeError | None
            with self._condition:
                if self._state == "ready":
                    ended_servers = self._retire_ended_servers_locked()
                    if exc.server_id in ended_servers:
                        final_snapshot = self._snapshot
                        final_error = None
                    else:
                        for server_id, generation in captured.items():
                            if server_id not in self._dead_servers:
                                self._published_generation[server_id] = generation
                        self._refresh_error = _runtime_error_copy(error)
                        final_error = error
                elif self._state == "failed" and self._failure is not None:
                    final_error = _runtime_error_copy(self._failure)
                    close_transport = True
                else:
                    final_error = self._closed_error()
                self._refreshing = False
                self._condition.notify_all()
            if close_transport:
                self._close_transport()
            if final_error is not None:
                raise _runtime_error_copy(final_error)
            assert final_snapshot is not None
            return final_snapshot
        except McpRuntimeError as exc:
            if exc.server_id is not None and self._isolate_server(exc.server_id):
                with self._condition:
                    if self._state == "ready":
                        self._refreshing = False
                        self._condition.notify_all()
                        return self._snapshot
            with self._condition:
                if self._state == "ready":
                    self._state = "failed"
                    self._failure = _runtime_error_copy(exc)
                    final_error = exc
                elif self._state == "failed" and self._failure is not None:
                    final_error = _runtime_error_copy(self._failure)
                else:
                    final_error = self._closed_error()
                self._refreshing = False
                self._condition.notify_all()
            self._close_transport()
            raise _runtime_error_copy(final_error)

        final_error: McpRuntimeError | None = None
        snapshot: tuple[McpToolDefinition, ...] = ()
        with self._condition:
            if self._state != "ready":
                final_error = (
                    _runtime_error_copy(self._failure)
                    if self._state == "failed" and self._failure is not None
                    else self._closed_error()
                )
            else:
                self._retire_ended_servers_locked()
                self._server_snapshots.update(
                    {
                        server_id: definitions
                        for server_id, definitions in discovered.items()
                        if server_id not in self._dead_servers
                    }
                )
                snapshot = self._combine_snapshots(self._server_snapshots)
                self._snapshot = snapshot
                self._known_targets.update(definition.target for definition in snapshot)
                for server_id, generation in captured.items():
                    if server_id not in self._dead_servers:
                        self._published_generation[server_id] = generation
                self._refresh_error = None
            self._refreshing = False
            self._condition.notify_all()
        if final_error is not None:
            self._close_transport()
            raise _runtime_error_copy(final_error)
        return snapshot

    def _combine_snapshots(
        self,
        snapshots: Mapping[str, tuple[McpToolDefinition, ...]],
    ) -> tuple[McpToolDefinition, ...]:
        return tuple(
            definition
            for config in self._configs
            for definition in snapshots.get(config.server_id, ())
        )

    def _ended_server_locked(self) -> str | None:
        ended_servers = self._ended_servers_locked()
        return min(ended_servers) if ended_servers else None

    def _ended_servers_locked(self) -> set[str]:
        return self._dead_servers | {
            server_id for server_id, owner in self._owners.items() if owner.done()
        }

    def _retire_ended_servers_locked(self) -> set[str]:
        ended_servers = self._ended_servers_locked()
        for server_id in ended_servers:
            self._retire_server_locked(server_id)
        return ended_servers

    def _start_loop(self, starts: tuple[_ServerStart, ...]) -> bool:
        with self._transport_lock:
            with self._condition:
                if self._state != "starting":
                    return False
            self._loop_ready.clear()
            self._loop_finished.clear()
            self._loop_failure = None
            self._thread = threading.Thread(
                target=self._thread_main,
                args=(starts,),
                name="agent-mcp-runtime",
                daemon=True,
            )
            self._thread.start()
        if not self._loop_ready.wait(_DISCOVERY_TIMEOUT_SECONDS):
            raise McpRuntimeError(
                stage="initialize",
                server_id=None,
                message="The MCP runtime loop did not start in time.",
            )
        if self._loop_failure is not None:
            raise _runtime_error_copy(self._loop_failure)
        return True

    def _thread_main(self, starts: tuple[_ServerStart, ...]) -> None:
        try:
            asyncio.run(self._loop_main(starts))
        except BaseException:
            error = McpRuntimeError(
                stage="initialize",
                server_id=None,
                message="The MCP runtime loop failed.",
            )
            self._loop_failure = error
            with self._condition:
                if self._state == "ready":
                    self._state = "failed"
                    self._failure = _runtime_error_copy(error)
                    self._refreshing = False
                    self._condition.notify_all()
        finally:
            self._loop_ready.set()
            self._loop_finished.set()

    async def _loop_main(self, starts: tuple[_ServerStart, ...]) -> None:
        import mcp

        loop = asyncio.get_running_loop()
        package_root = Path(mcp.__file__).resolve().parent
        log_filter = _McpLogFilter(
            owner_thread_id=threading.get_ident(),
            package_root=package_root,
        )
        loggers = [logging.getLogger(), *(logging.getLogger(name) for name in _MCP_LOGGERS)]
        for logger in loggers:
            logger.addFilter(log_filter)
        try:
            with self._transport_lock:
                self._loop = loop
                if self._transport_closing:
                    self._loop_ready.set()
                    return
                self._queues = {start.config.server_id: asyncio.Queue() for start in starts}
                self._stop_event = asyncio.Event()
                self._owners = {
                    start.config.server_id: asyncio.create_task(
                        self._server_owner(start, self._queues[start.config.server_id]),
                        name=f"mcp-owner-{start.config.server_id}",
                    )
                    for start in starts
                }
                for server_id, owner in self._owners.items():
                    owner.add_done_callback(
                        lambda _task, server_id=server_id: self._owner_finished(server_id)
                    )
                self._loop_ready.set()
            await self._stop_event.wait()
            for owner in self._owners.values():
                if not owner.done():
                    owner.cancel()
            await asyncio.gather(*self._owners.values(), return_exceptions=True)
        finally:
            for logger in loggers:
                logger.removeFilter(log_filter)
    def _owner_finished(self, server_id: str) -> None:
        with self._condition:
            if self._state == "ready":
                self._retire_server_locked(server_id)
            else:
                self._dead_servers.add(server_id)
            self._condition.notify_all()

    @staticmethod
    async def _wait_for_session_end(read_stream: Any, write_stream: Any) -> None:
        while (
            read_stream.statistics().open_send_streams
            and write_stream.statistics().open_send_streams
        ):
            await asyncio.sleep(0.05)

    async def _next_owner_command(
        self,
        queue: asyncio.Queue[_OwnerCommand],
        disconnect_task: asyncio.Task[None],
        *,
        server_id: str,
    ) -> _OwnerCommand:
        command_task = asyncio.create_task(queue.get())
        try:
            done, _ = await asyncio.wait(
                {command_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if command_task in done:
                return command_task.result()
            raise McpRuntimeError(
                stage="discovery",
                server_id=server_id,
                message="The MCP server session ended unexpectedly.",
            )
        finally:
            if not command_task.done():
                command_task.cancel()
            await asyncio.gather(command_task, return_exceptions=True)


    async def _server_owner(
        self,
        start: _ServerStart,
        queue: asyncio.Queue[_OwnerCommand],
    ) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import mcp.types as types

        current: _OwnerCommand | None = None
        close_future: concurrent.futures.Future[Any] | None = None
        initialized = False

        async def message_handler(message: Any) -> None:
            if isinstance(message, Exception):
                raise _McpProtocolError("Invalid MCP protocol message.")
            if (
                isinstance(message, types.ServerNotification)
                and isinstance(message.root, types.ToolListChangedNotification)
            ):
                self._mark_dirty(start.config.server_id)

        try:
            current = await queue.get()
            if current.kind == "close":
                close_future = current.future
                current = None
                return
            parameters = StdioServerParameters(
                command=str(start.config.command),
                args=list(start.config.args),
                env=dict(start.environment),
                cwd=start.config.cwd,
            )
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(parameters, errlog=errlog) as (read_stream, write_stream):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=None,
                        message_handler=message_handler,
                    ) as session:
                        disconnect_task = asyncio.create_task(
                            self._wait_for_session_end(read_stream, write_stream)
                        )
                        try:
                            async with asyncio.timeout(_DISCOVERY_TIMEOUT_SECONDS):
                                initialization = await session.initialize()
                        except Exception:
                            raise McpRuntimeError(
                                stage="discovery",
                                server_id=start.config.server_id,
                                message="The MCP server failed protocol initialization.",
                            ) from None
                        if initialization.capabilities.tools is None:
                            _set_future_exception(
                                current.future,
                                McpRuntimeError(
                                    stage="discovery",
                                    server_id=start.config.server_id,
                                    message="The MCP server does not declare the tools capability.",
                                ),
                            )
                            return
                        initialized = True
                        while current is not None:
                            if current.kind == "discover":
                                try:
                                    async with asyncio.timeout(_DISCOVERY_TIMEOUT_SECONDS):
                                        definitions = await self._list_tools(session, start)
                                except _SnapshotSafetyError as exc:
                                    _set_future_exception(current.future, exc)
                                    if current.initial:
                                        return
                                except Exception:
                                    _set_future_exception(
                                        current.future,
                                        McpRuntimeError(
                                            stage="discovery",
                                            server_id=start.config.server_id,
                                            message="The MCP server failed tool discovery.",
                                        ),
                                    )
                                    return
                                else:
                                    _set_future_result(current.future, definitions)
                            elif current.kind == "call" and current.try_start():
                                try:
                                    outcome = await self._call_remote_tool(session, start, current)
                                finally:
                                    current.finish()
                                _set_future_result(current.future, outcome.result)
                                if outcome.poison_server:
                                    return

                            current = await self._next_owner_command(
                                queue,
                                disconnect_task,
                                server_id=start.config.server_id,
                            )
                            if current.kind == "close":
                                close_future = current.future
                                current = None
        except asyncio.CancelledError:
            raise
        except McpRuntimeError as exc:
            if current is not None:
                _set_future_exception(current.future, _runtime_error_copy(exc))
        except Exception:
            if current is not None:
                _set_future_exception(
                    current.future,
                    McpRuntimeError(
                        stage="discovery" if initialized else "initialize",
                        server_id=start.config.server_id,
                        message="The MCP server could not be started.",
                    ),
                )
        finally:
            if current is not None:
                _set_future_exception(current.future, self._closed_error())
            while not queue.empty():
                command = queue.get_nowait()
                if command.kind == "close":
                    close_future = command.future
                else:
                    _set_future_exception(command.future, self._closed_error())
            if close_future is not None:
                _set_future_result(close_future, None)

    async def _call_remote_tool(
        self,
        session: Any,
        start: _ServerStart,
        command: _OwnerCommand,
    ) -> _OwnerCallOutcome:
        import mcp.types as types

        target = command.target
        if target is None:
            return _OwnerCallOutcome(
                _call_failure_result(
                    status="failed",
                    summary="MCP tool target is unavailable.",
                    stage="routing",
                ),
                poison_server=True,
            )
        try:
            request = types.ClientRequest(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(
                        name=target.remote_name,
                        arguments=command.arguments or {},
                    )
                )
            )
            raw_result = await session.send_request(request, types.CallToolResult)
            return _normalize_call_result(raw_result, target, start.secrets)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            return _OwnerCallOutcome(
                _call_failure_result(
                    status="timeout",
                    summary="MCP tool call timed out.",
                    stage="request_timeout",
                    secrets=start.secrets,
                    error=exc,
                ),
                poison_server=True,
            )
        except Exception as exc:
            return _OwnerCallOutcome(
                _call_failure_result(
                    status="failed",
                    summary="MCP tool call failed.",
                    stage="request",
                    secrets=start.secrets,
                    error=exc,
                ),
                poison_server=True,
            )

    async def _list_tools(self, session: Any, start: _ServerStart) -> tuple[McpToolDefinition, ...]:
        import mcp.types as types

        tools = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            page = (
                await session.list_tools()
                if cursor is None
                else await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            )
            page_count += 1
            if page_count > _MAX_DISCOVERY_PAGES:
                raise _McpProtocolError("The MCP server returned too many tools/list pages.")
            if len(page.tools) > _MAX_TOOLS_PER_SERVER - len(tools):
                raise _McpProtocolError("The MCP server returned too many tools.")
            tools.extend(page.tools)
            next_cursor = page.nextCursor
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise _McpProtocolError("The MCP server repeated a tools/list cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return _definitions_from_tools(start.config.server_id, tools, start.secrets)

    def _dispatch_discovery(
        self,
        server_ids: tuple[str, ...],
        *,
        initial: bool,
    ) -> dict[str, tuple[McpToolDefinition, ...]]:
        futures: dict[str, concurrent.futures.Future[Any]] = {}
        for server_id in server_ids:
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            futures[server_id] = future
            self._enqueue(server_id, _OwnerCommand(kind="discover", future=future, initial=initial))

        # The owner may legally spend the full per-phase budget twice
        # (initialize + list_tools each run under asyncio.timeout of
        # _DISCOVERY_TIMEOUT_SECONDS), so the dispatcher must wait at least
        # that long or a slow-but-legal server times out from the caller side.
        deadline = time.monotonic() + 2 * _DISCOVERY_TIMEOUT_SECONDS + 1.0
        results: dict[str, tuple[McpToolDefinition, ...]] = {}
        safety_errors: list[_SnapshotSafetyError] = []
        runtime_errors: list[McpRuntimeError] = []
        for server_id, future in futures.items():
            try:
                remaining = max(0.0, deadline - time.monotonic())
                results[server_id] = future.result(timeout=remaining)
            except _SnapshotSafetyError as exc:
                safety_errors.append(exc)
            except McpRuntimeError as exc:
                runtime_errors.append(exc)
            except Exception:
                runtime_errors.append(
                    McpRuntimeError(
                        stage="discovery",
                        server_id=server_id,
                        message="The MCP server did not complete tool discovery.",
                    )
                )
        if runtime_errors:
            raise _runtime_error_copy(runtime_errors[0])
        if safety_errors:
            raise safety_errors[0]
        return results

    def _enqueue(self, server_id: str, command: _OwnerCommand) -> None:
        loop = self._loop
        if loop is None:
            _set_future_exception(command.future, self._closed_error())
            return

        def enqueue() -> None:
            owner = self._owners.get(server_id)
            queue = self._queues.get(server_id)
            if owner is None or queue is None or owner.done():
                if command.kind == "close":
                    _set_future_result(command.future, None)
                else:
                    _set_future_exception(
                        command.future,
                        McpRuntimeError(
                            stage="call" if command.kind == "call" else "discovery",
                            server_id=server_id,
                            message="The MCP server session is not available.",
                        ),
                    )
                return
            queue.put_nowait(command)

        try:
            loop.call_soon_threadsafe(enqueue)
        except RuntimeError:
            _set_future_exception(command.future, self._closed_error())

    def _mark_dirty(self, server_id: str) -> None:
        with self._condition:
            if self._state in {"starting", "ready"} and server_id not in self._dead_servers:
                self._dirty_generation[server_id] = self._dirty_generation.get(server_id, 0) + 1
                self._condition.notify_all()

    def _transport_stopped(self) -> bool:
        thread = self._thread
        return thread is None or not thread.is_alive()


    def _request_transport_stop(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is None or stop_event is None:
            return
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass


    def _close_transport(self) -> None:
        deadline = time.monotonic() + _CLOSE_TIMEOUT_SECONDS
        with self._transport_lock:
            if self._transport_closing:
                wait_for_existing = True
            else:
                self._transport_closing = True
                wait_for_existing = False
            thread = self._thread
        if thread is None:
            self._loop_finished.set()
            return
        if wait_for_existing:
            if not self._loop_finished.wait(max(0.0, deadline - time.monotonic())):
                raise _transport_cleanup_error()
            return

        try:
            close_futures = []
            ready_timeout = max(0.0, deadline - time.monotonic())
            if self._loop_ready.wait(ready_timeout) and self._loop_failure is None:
                for server_id in tuple(self._starts):
                    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
                    close_futures.append(future)
                    self._enqueue(server_id, _OwnerCommand(kind="close", future=future))

            for future in close_futures:
                try:
                    future.result(timeout=max(0.0, deadline - time.monotonic()))
                except Exception:
                    break
        finally:
            self._request_transport_stop()
            thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            raise _transport_cleanup_error()

    @staticmethod
    def _closed_error() -> McpRuntimeError:
        return McpRuntimeError(stage="runtime", server_id=None, message="The MCP runtime is closed.")

__all__ = [
    "McpCallResult",
    "McpCallStatus",
    "McpRuntimeError",
    "McpStdioRuntime",
    "McpServerConfig",
    "McpToolDefinition",
    "McpToolTarget",
    "build_mcp_tool_name",
    "load_mcp_server_configs",
]
