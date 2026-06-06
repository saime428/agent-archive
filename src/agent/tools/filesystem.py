from __future__ import annotations

from pathlib import Path

from agent.core.actions import (
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
)
from agent.core.context import RunContext
from agent.policy.sandbox import SandboxError, WorkspaceSandbox

DEFAULT_MAX_LINES = 200
DEFAULT_MAX_CHARS = 20_000


def execute_tool(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    try:
        if action.action.name == "list_dir":
            return _list_dir(action, sandbox, observation_index=observation_index)
        if action.action.name == "read_file":
            return _read_file(action, sandbox, observation_index=observation_index)
    except SandboxError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    except OSError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=str(exc),
            details={"tool": action.action.name},
        )

    return make_error_observation(
        action.action_id,
        context.run_id,
        observation_index=observation_index,
        code=ErrorCode.POLICY_DENIED,
        message="Unsupported tool.",
        details={"requested_action": action.action.name},
    )


def _list_dir(
    action: InternalAction,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    path = sandbox.resolve_read_path(str(action.action.args["path"]))
    if not path.is_dir():
        raise OSError(f"Not a directory: {path}")

    entries = sorted(path.iterdir(), key=lambda item: item.name.lower())
    max_entries = action.action.args.get("max_entries")
    visible_entries = entries[:max_entries] if max_entries is not None else entries
    data = {
        "path": str(path),
        "total_entries": len(entries),
        "truncated": max_entries is not None and len(entries) > max_entries,
        "entries": [
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
            for item in visible_entries
        ],
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Listed {len(visible_entries)} of {len(entries)} entries.",
        data=data,
    )


def _read_file(
    action: InternalAction,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    path = sandbox.resolve_read_path(str(action.action.args["path"]))
    if not path.is_file():
        raise OSError(f"Not a file: {path}")

    raw = path.read_bytes()
    if _looks_binary(raw):
        return make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message="Binary files are not supported by read_file.",
            details={"path": str(path)},
        )

    text = _decode_text(raw)
    lines = text.splitlines()
    total_lines = len(lines)
    start_line = action.action.args.get("start_line") or 1
    requested_max_lines = action.action.args.get("max_lines")
    max_lines = requested_max_lines or DEFAULT_MAX_LINES
    start_index = max(start_line - 1, 0)
    selected_lines = lines[start_index : start_index + max_lines]
    content = "\n".join(selected_lines)
    truncated = requested_max_lines is None and start_index + len(selected_lines) < total_lines
    if len(content) > DEFAULT_MAX_CHARS:
        content = content[:DEFAULT_MAX_CHARS]
        truncated = True
    if truncated:
        content = f"{content}\n[truncated]" if content else "[truncated]"
    end_line = start_line + len(selected_lines) - 1 if selected_lines else start_line - 1

    data = {
        "path": str(path),
        "content": content,
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": total_lines,
        "byte_size": len(raw),
        "truncated": truncated,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Read {len(selected_lines)} lines from file.",
        data=data,
    )


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:4096]


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")
