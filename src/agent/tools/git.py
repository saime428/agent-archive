from __future__ import annotations

import subprocess

from agent.core.actions import (
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
)
from agent.core.budget import ContextBudget, truncate_text
from agent.core.context import RunContext
from agent.policy.sandbox import SandboxError, WorkspaceSandbox

DEFAULT_MAX_CHARS = ContextBudget().git_output_chars
DEFAULT_TIMEOUT_SECONDS = 30


def execute_git_tool(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    try:
        _ensure_workspace_git_repo(context.cwd)
        argv = _build_argv(action, context, sandbox)
        completed = subprocess.run(
            argv,
            cwd=context.cwd,
            shell=False,
            capture_output=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except SandboxError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    except subprocess.TimeoutExpired as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TIMEOUT,
            message="Git command timed out.",
            details={
                "argv": exc.cmd,
                "cwd": str(context.cwd),
                "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                "stdout": _truncate(
                    _decode_output(exc.stdout or b""),
                    _max_chars(action, context),
                )[0],
                "stderr": _truncate(
                    _decode_output(exc.stderr or b""),
                    _max_chars(action, context),
                )[0],
            },
        )
    except OSError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=str(exc),
            details={"tool": action.action.name, "cwd": str(context.cwd)},
        )

    stdout, stdout_truncated = _truncate(_decode_output(completed.stdout), _max_chars(action, context))
    stderr, stderr_truncated = _truncate(_decode_output(completed.stderr), _max_chars(action, context))
    data = {
        "argv": argv,
        "cwd": str(context.cwd),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    if completed.returncode != 0:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=f"Git command exited with code {completed.returncode}.",
            details=data,
        )

    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Git command exited with code {completed.returncode}.",
        data=data,
    )


def _build_argv(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
) -> list[str]:
    if action.action.name == "git_status":
        return ["git", "status", "--short"] if action.action.args["short"] else ["git", "status"]
    if action.action.name == "git_diff":
        argv = ["git", "diff"]
        if action.action.args["cached"]:
            argv.append("--cached")
        path = action.action.args.get("path")
        if path is not None:
            argv.extend(["--", _git_relative_path(str(path), context, sandbox)])
        return argv
    raise ValueError(f"Unsupported git action: {action.action.name}")


def _ensure_workspace_git_repo(cwd) -> None:
    if not (cwd / ".git").exists():
        raise OSError("Workspace is not a git repository.")


def _git_relative_path(path: str, context: RunContext, sandbox: WorkspaceSandbox) -> str:
    resolved = sandbox.resolve_read_path(path, allow_external=False)
    try:
        return resolved.relative_to(context.cwd).as_posix()
    except ValueError as exc:
        raise SandboxError(
            ErrorCode.SANDBOX_VIOLATION,
            "Path resolves outside the workspace.",
            {"path": path},
        ) from exc


def _max_chars(action: InternalAction, context: RunContext) -> int:
    budget_limit = context.budget.git_output_chars
    if action.action.name != "git_diff":
        return budget_limit
    requested = action.action.args.get("max_bytes")
    return min(requested or budget_limit, budget_limit)


def _decode_output(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return _normalize_newlines(raw)
    try:
        return _normalize_newlines(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return _normalize_newlines(raw.decode("utf-8", errors="replace"))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    result = truncate_text(text, max_chars)
    return result.value, result.truncated
