from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal


McpCallStatus = Literal["ok", "tool_error", "timeout", "failed"]

_MAX_SERVERS = 8
_SERVER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_SERVER_FIELDS = {"command", "args", "pass_env", "cwd"}
_WINDOWS_NATIVE_EXTENSIONS = {".COM", ".EXE"}
_STARTUP_PATH = os.environ.get("PATH", "")
_STARTUP_PATHEXT = os.environ.get("PATHEXT")


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


__all__ = [
    "McpCallResult",
    "McpCallStatus",
    "McpRuntimeError",
    "McpServerConfig",
    "McpToolDefinition",
    "McpToolTarget",
    "build_mcp_tool_name",
    "load_mcp_server_configs",
]
