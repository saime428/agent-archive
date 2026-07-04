from __future__ import annotations

import os
import subprocess
from pathlib import Path

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

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = ContextBudget().command_output_chars

SHELL_WRAPPERS = {
    "bash",
    "bash.exe",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "sh.exe",
    "wsl",
    "wsl.exe",
}
NETWORK_COMMANDS = {
    "curl",
    "curl.exe",
    "invoke-restmethod",
    "invoke-webrequest",
    "iwr",
    "irm",
    "rsync",
    "rsync.exe",
    "scp",
    "scp.exe",
    "ssh",
    "ssh.exe",
    "wget",
    "wget.exe",
}
DANGEROUS_COMMANDS = {
    "del",
    "erase",
    "format",
    "format.com",
    "mkfs",
    "rd",
    "reg",
    "remove-item",
    "ri",
    "rm",
    "rm.exe",
    "rmdir",
    "shutdown",
    "takeown",
}
PYTHON_COMMANDS = {"py", "py.exe", "python", "python.exe", "python3", "python3.exe"}
GIT_READ_ONLY_SUBCOMMANDS = {
    "--version",
    "diff",
    "log",
    "rev-parse",
    "show",
    "status",
}


def execute_run_command(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    argv = [str(item) for item in action.action.args["argv"]]
    timeout_seconds = _bounded_timeout(action.action.args.get("timeout_seconds"))
    cwd = context.cwd
    try:
        cwd = _resolve_cwd(action, context, sandbox)
        denial = _policy_denial(argv)
        if denial is not None:
            return make_error_observation(
                action.action_id,
                action.run_id,
                observation_index=observation_index,
                code=ErrorCode.POLICY_DENIED,
                message=denial,
                details={"argv": argv},
            )
        _validate_path_arguments(argv, sandbox)
        completed = subprocess.run(
            argv,
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
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
            message="Command timed out.",
            details={
                "argv": argv,
                "cwd": str(cwd),
                "timeout_seconds": timeout_seconds,
                "stdout": _truncate(
                    _decode_output(exc.stdout or b""),
                    context.budget.command_output_chars,
                )[0],
                "stderr": _truncate(
                    _decode_output(exc.stderr or b""),
                    context.budget.command_output_chars,
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
            details={"argv": argv, "cwd": str(cwd)},
        )

    stdout, stdout_truncated = _truncate(_decode_output(completed.stdout), context.budget.command_output_chars)
    stderr, stderr_truncated = _truncate(_decode_output(completed.stderr), context.budget.command_output_chars)
    data = {
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Command exited with code {completed.returncode}.",
        data=data,
    )


def _resolve_cwd(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
) -> Path:
    requested_cwd = action.action.args.get("cwd")
    if requested_cwd is None:
        return context.cwd
    cwd = sandbox.resolve_read_path(
        str(requested_cwd),
        allow_external=sandbox.allow_external_read,
    )
    if not cwd.is_dir():
        raise OSError(f"Command cwd is not a directory: {cwd}")
    return cwd


def _bounded_timeout(raw_timeout: int | None) -> int:
    timeout = raw_timeout or DEFAULT_TIMEOUT_SECONDS
    return min(timeout, MAX_TIMEOUT_SECONDS)


def _policy_denial(argv: list[str]) -> str | None:
    executable = _executable_name(argv[0])
    if executable in SHELL_WRAPPERS:
        return "Shell wrapper commands are not supported."
    if executable in NETWORK_COMMANDS:
        return "Network commands are disabled by policy."
    if executable in DANGEROUS_COMMANDS:
        return "Dangerous commands are denied by policy."
    if executable in {"git", "git.exe"}:
        return _git_policy_denial(argv)
    if executable in PYTHON_COMMANDS:
        return _python_policy_denial(argv)
    if executable in {"pytest", "pytest.exe", "rg", "rg.exe"}:
        return None
    return "Command is not allowed by default."


def _validate_path_arguments(argv: list[str], sandbox: WorkspaceSandbox) -> None:
    if _executable_name(argv[0]) in PYTHON_COMMANDS and len(argv) >= 2 and argv[1] == "-c":
        return

    for arg in argv[1:]:
        if arg == "--" or arg.startswith("-"):
            continue
        if _looks_like_path_argument(arg):
            sandbox.resolve_read_path(arg, allow_external=sandbox.allow_external_read)


def _looks_like_path_argument(arg: str) -> bool:
    return (
        arg in {".", ".."}
        or arg.startswith(".")
        or "/" in arg
        or "\\" in arg
        or Path(arg).is_absolute()
    )


def _git_policy_denial(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "Git command must include a read-only subcommand."
    subcommand = argv[1].lower()
    if subcommand in GIT_READ_ONLY_SUBCOMMANDS:
        return None
    return "Only read-only git commands are allowed by default."


def _python_policy_denial(argv: list[str]) -> str | None:
    if len(argv) >= 2 and argv[1] == "-c":
        return None
    if len(argv) >= 3 and argv[1] == "-m" and argv[2] == "pytest":
        return None
    return "Only Python one-liners and pytest module runs are allowed by default."


def _executable_name(executable: str) -> str:
    return os.path.basename(executable).lower()


def _decode_output(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return _normalize_newlines(raw)
    try:
        return _normalize_newlines(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return _normalize_newlines(raw.decode("utf-8", errors="replace"))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    result = truncate_text(text, max_chars)
    return result.value, result.truncated
