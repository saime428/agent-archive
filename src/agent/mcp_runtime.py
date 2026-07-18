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
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urljoin

McpCallStatus = Literal["ok", "tool_error", "timeout", "failed"]

_MAX_SERVERS = 8
_SERVER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_SERVER_FIELDS = {"command", "args", "pass_env", "cwd"}
_WINDOWS_NATIVE_EXTENSIONS = {".COM", ".EXE"}
_STARTUP_PATH = os.environ.get("PATH", "")
_STARTUP_PATHEXT = os.environ.get("PATHEXT")
_DISCOVERY_TIMEOUT_SECONDS = 15.0
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


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    server_id: str
    command: Path
    args: tuple[str, ...]
    pass_env: tuple[str, ...]
    cwd: Path
    subprocess_path: str
    subprocess_pathext: str | None


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


class McpRuntimeError(RuntimeError):
    def __init__(self, *, stage: str, server_id: str | None, message: str) -> None:
        self.stage = stage
        self.server_id = server_id
        self.message = message
        prefix = f"MCP {stage} failed"
        if server_id is not None:
            prefix += f" for server {server_id!r}"
        super().__init__(f"{prefix}: {message}")


def load_mcp_server_configs(
    workspace: Path,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[McpServerConfig, ...]:
    workspace_path = _resolve_workspace(workspace)
    try:
        home_path = (home or Path.home()).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise _config_error("User home directory cannot be resolved.") from exc
    config_path = home_path / ".agent" / "mcp.toml"
    if not config_path.exists() and not config_path.is_symlink():
        return ()

    resolved_config, config_dir = _resolve_config_path(config_path, workspace_path)
    values = _read_toml(resolved_config)
    unknown_root_fields = set(values) - {"servers"}
    if unknown_root_fields:
        names = ", ".join(sorted(unknown_root_fields))
        raise _config_error(f"Unknown top-level field(s): {names}.")

    servers = values.get("servers", {})
    if not isinstance(servers, dict):
        raise _config_error("The 'servers' field must be a TOML table.")
    if len(servers) > _MAX_SERVERS:
        raise _config_error(f"At most {_MAX_SERVERS} MCP servers may be configured.")

    path_value = _STARTUP_PATH if environ is None else (_environment_value(environ, "PATH") or "")
    pathext_value = _STARTUP_PATHEXT if environ is None else _environment_value(environ, "PATHEXT")
    path_entries = _canonical_path_entries(path_value, workspace_path)
    path_extensions = _windows_path_extensions(pathext_value)
    subprocess_path = os.pathsep.join(str(path) for path in path_entries)
    subprocess_pathext = ";".join(path_extensions) if os.name == "nt" else None

    configs = []
    for server_id, server_values in servers.items():
        configs.append(
            _parse_server_config(
                server_id,
                server_values,
                workspace=workspace_path,
                config_dir=config_dir,
                path_entries=path_entries,
                path_extensions=path_extensions,
                subprocess_path=subprocess_path,
                subprocess_pathext=subprocess_pathext,
            )
        )
    if configs and not path_entries:
        raise _config_error("Sanitized PATH must contain at least one absolute directory outside the workspace.")
    return tuple(configs)


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


def _resolve_workspace(workspace: Path) -> Path:
    try:
        resolved = workspace.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _config_error("Workspace does not exist or cannot be resolved.") from exc
    if not resolved.is_dir():
        raise _config_error("Workspace must be a directory.")
    return resolved


def _resolve_config_path(config_path: Path, workspace: Path) -> tuple[Path, Path]:
    try:
        config_dir = config_path.parent.resolve(strict=True)
        resolved_config = config_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _config_error("User MCP configuration cannot be resolved.") from exc
    if _is_within(config_dir, workspace) or _is_within(resolved_config, workspace):
        raise _config_error("User MCP configuration must not resolve inside the workspace.")
    if not resolved_config.is_file():
        raise _config_error("User MCP configuration must be a file.")
    return resolved_config, config_dir


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise _config_error("Could not parse user MCP configuration.") from exc
    except OSError as exc:
        raise _config_error("Could not read user MCP configuration.") from exc
    return values


def _parse_server_config(
    server_id: Any,
    values: Any,
    *,
    workspace: Path,
    config_dir: Path,
    path_entries: tuple[Path, ...],
    path_extensions: tuple[str, ...],
    subprocess_path: str,
    subprocess_pathext: str | None,
) -> McpServerConfig:
    if not isinstance(server_id, str) or _SERVER_ID_PATTERN.fullmatch(server_id) is None:
        raise _config_error("Server ID must contain only ASCII letters, digits, '_' or '-'.")
    if not isinstance(values, dict):
        raise _config_error("Server configuration must be a TOML table.", server_id=server_id)
    unknown_fields = set(values) - _SERVER_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise _config_error(f"Unknown server field(s): {names}.", server_id=server_id)

    command = values.get("command")
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise _config_error("'command' must be a non-empty string.", server_id=server_id)
    args = _string_list(values.get("args", []), field="args", server_id=server_id)
    pass_env = _pass_env_names(values.get("pass_env", []), server_id=server_id)
    cwd_mode = values.get("cwd", "config")
    if not isinstance(cwd_mode, str) or cwd_mode not in {"config", "workspace"}:
        raise _config_error("'cwd' must be either 'config' or 'workspace'.", server_id=server_id)

    resolved_command = _resolve_command(
        command,
        workspace=workspace,
        path_entries=path_entries,
        path_extensions=path_extensions,
        server_id=server_id,
    )
    expanded_args = tuple(str(workspace) if value == "{workspace}" else value for value in args)
    return McpServerConfig(
        server_id=server_id,
        command=resolved_command,
        args=expanded_args,
        pass_env=pass_env,
        cwd=config_dir if cwd_mode == "config" else workspace,
        subprocess_path=subprocess_path,
        subprocess_pathext=subprocess_pathext,
    )


def _string_list(value: Any, *, field: str, server_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _config_error(f"'{field}' must be an array of strings.", server_id=server_id)
    if any("\x00" in item for item in value):
        raise _config_error(f"'{field}' must not contain NUL characters.", server_id=server_id)
    return tuple(value)


def _pass_env_names(value: Any, *, server_id: str) -> tuple[str, ...]:
    names = _string_list(value, field="pass_env", server_id=server_id)
    seen: set[str] = set()
    for name in names:
        if _ENV_NAME_PATTERN.fullmatch(name) is None:
            raise _config_error(f"Invalid pass_env variable name: {name!r}.", server_id=server_id)
        comparison = name.casefold() if os.name == "nt" else name
        reserved = {item.casefold() if os.name == "nt" else item for item in ("PATH", "PATHEXT")}
        if comparison in reserved:
            raise _config_error(f"pass_env variable {name!r} is reserved.", server_id=server_id)
        if comparison in seen:
            raise _config_error(f"Duplicate pass_env variable: {name!r}.", server_id=server_id)
        seen.add(comparison)
    return names


def _resolve_command(
    command: str,
    *,
    workspace: Path,
    path_entries: tuple[Path, ...],
    path_extensions: tuple[str, ...],
    server_id: str,
) -> Path:
    command_path = Path(command)
    if command_path.is_absolute():
        try:
            resolved = command_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _config_error("Absolute command must resolve to an existing file.", server_id=server_id) from exc
        if not resolved.is_file():
            raise _config_error("Absolute command must resolve to an existing file.", server_id=server_id)
        _require_native_windows_command(resolved, server_id=server_id)
        return resolved

    if _has_path_syntax(command):
        raise _config_error("Relative command paths are not allowed.", server_id=server_id)

    candidate_names = _command_candidate_names(command, path_extensions, server_id=server_id)
    for directory in path_entries:
        for candidate_name in candidate_names:
            candidate = directory / candidate_name
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if (
                not resolved.is_file()
                or _is_within(resolved, workspace)
                or not _is_native_windows_command(resolved)
            ):
                continue
            if os.name != "nt" and not os.access(resolved, os.X_OK):
                continue
            return resolved
    raise _config_error(f"Bare command {command!r} was not found in the sanitized PATH.", server_id=server_id)


def _has_path_syntax(command: str) -> bool:
    windows_path = PureWindowsPath(command)
    return command in {".", ".."} or "/" in command or "\\" in command or bool(windows_path.drive or windows_path.root)


def _command_candidate_names(command: str, path_extensions: tuple[str, ...], *, server_id: str) -> tuple[str, ...]:
    if os.name != "nt":
        return (command,)
    suffix = PureWindowsPath(command).suffix.upper()
    if suffix:
        if suffix not in _WINDOWS_NATIVE_EXTENSIONS:
            raise _config_error("Windows command must be a native executable (.exe or .com).", server_id=server_id)
        return (command,)
    return tuple(f"{command}{extension.lower()}" for extension in path_extensions)


def _require_native_windows_command(path: Path, *, server_id: str) -> None:
    if not _is_native_windows_command(path):
        raise _config_error("Windows command must be a native executable (.exe or .com).", server_id=server_id)


def _is_native_windows_command(path: Path) -> bool:
    return os.name != "nt" or path.suffix.upper() in _WINDOWS_NATIVE_EXTENSIONS


def _canonical_path_entries(value: str, workspace: Path) -> tuple[Path, ...]:
    entries = []
    seen: set[str] = set()
    for raw_entry in value.split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        if not entry.is_absolute():
            continue
        try:
            resolved = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir() or os.pathsep in str(resolved) or _is_within(resolved, workspace):
            continue
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        entries.append(resolved)
    return tuple(entries)


def _windows_path_extensions(value: str | None) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    extensions = []
    seen: set[str] = set()
    for raw_extension in (value or "").split(";"):
        extension = raw_extension.strip().upper()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        if extension not in _WINDOWS_NATIVE_EXTENSIONS or extension in seen:
            continue
        seen.add(extension)
        extensions.append(extension)
    return tuple(extensions)


def _environment_value(environ: Mapping[str, str], name: str) -> str | None:
    if os.name != "nt":
        return environ.get(name)
    folded_name = name.casefold()
    return next((value for key, value in environ.items() if key.casefold() == folded_name), None)


def _is_within(path: Path, root: Path) -> bool:
    path_text = _comparison_path(path)
    root_text = _comparison_path(root)
    try:
        if os.path.commonpath([path_text, root_text]) == root_text:
            return True
    except ValueError:
        pass
    for candidate in (path, *path.parents):
        try:
            if candidate.samefile(root):
                return True
        except OSError:
            return True
    return False


def _comparison_path(path: Path) -> str:
    value = os.path.normcase(os.path.normpath(str(path)))
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\unc\\"):
        return f"\\\\{value[8:]}"
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _config_error(message: str, *, server_id: str | None = None) -> McpRuntimeError:
    return McpRuntimeError(stage="config", server_id=server_id, message=message)



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
    kind: Literal["discover", "close"]
    future: concurrent.futures.Future[Any]
    initial: bool = False


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
                        if self._dirty_generation.get(config.server_id, 0)
                        > self._published_generation.get(config.server_id, 0)
                    }
                    if captured and self._refresh_error is not None:
                        captured = {
                            config.server_id: self._dirty_generation.get(config.server_id, 0)
                            for config in self._configs
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
        try:
            self._close_transport()
        except McpRuntimeError:
            pass


    def _finish_close_locked(self) -> None:
        self._state = "closed"
        self._failure = None
        self._snapshot = ()
        self._server_snapshots.clear()
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
            configs = load_mcp_server_configs(
                self._workspace,
                home=self._home,
                environ=self._environ,
            )
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
            with self._condition:
                dead_server = self._ended_server_locked()
                if self._state == "ready" and dead_server is None:
                    for server_id, generation in captured.items():
                        self._published_generation[server_id] = generation
                    self._refresh_error = _runtime_error_copy(error)
                    final_error = error
                elif self._state == "ready":
                    assert dead_server is not None
                    final_error = _session_ended_error(dead_server)
                    self._state = "failed"
                    self._failure = _runtime_error_copy(final_error)
                    close_transport = True
                elif self._state == "failed" and self._failure is not None:
                    final_error = _runtime_error_copy(self._failure)
                    close_transport = True
                else:
                    final_error = self._closed_error()
                self._refreshing = False
                self._condition.notify_all()
            if close_transport:
                self._close_transport()
            raise _runtime_error_copy(final_error)
        except McpRuntimeError as exc:
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

        snapshots = dict(self._server_snapshots)
        snapshots.update(discovered)
        snapshot = self._combine_snapshots(snapshots)
        final_error: McpRuntimeError | None = None
        with self._condition:
            dead_server = self._ended_server_locked()
            if self._state != "ready":
                final_error = (
                    _runtime_error_copy(self._failure)
                    if self._state == "failed" and self._failure is not None
                    else self._closed_error()
                )
            elif dead_server is not None:
                final_error = _session_ended_error(dead_server)
                self._state = "failed"
                self._failure = _runtime_error_copy(final_error)
            else:
                self._server_snapshots = snapshots
                self._snapshot = snapshot
                for server_id, generation in captured.items():
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
        ended_servers = self._dead_servers | {
            server_id for server_id, owner in self._owners.items() if owner.done()
        }
        return min(ended_servers) if ended_servers else None

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
            self._dead_servers.add(server_id)
            if self._state != "ready" or self._refreshing:
                return
            self._state = "failed"
            self._failure = _session_ended_error(server_id)
            self._condition.notify_all()
        if self._stop_event is not None:
            self._stop_event.set()

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
                        read_timeout_seconds=timedelta(seconds=_DISCOVERY_TIMEOUT_SECONDS),
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

        deadline = time.monotonic() + _DISCOVERY_TIMEOUT_SECONDS + 1.0
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
                            stage="discovery",
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
            if self._state in {"starting", "ready"}:
                self._dirty_generation[server_id] = self._dirty_generation.get(server_id, 0) + 1
                self._condition.notify_all()

    def _transport_stopped(self) -> bool:
        thread = self._thread
        return thread is None or not thread.is_alive()


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
            loop = self._loop
            stop_event = self._stop_event
            if loop is not None and stop_event is not None:
                try:
                    loop.call_soon_threadsafe(stop_event.set)
                except RuntimeError:
                    pass
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
