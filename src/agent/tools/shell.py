from __future__ import annotations

import os
import signal
import subprocess
import time
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
from agent.core.run_control import RunControl, StopReason
from agent.policy.sandbox import SandboxError, WorkspaceSandbox

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = ContextBudget().command_output_chars
PROCESS_POLL_SECONDS = 0.05
PROCESS_STOP_SECONDS = 5.0

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
    allowed_commands: tuple[str, ...] = (),
    control: RunControl | None = None,
) -> Observation:
    argv = [str(item) for item in action.action.args["argv"]]
    timeout_seconds = _bounded_timeout(action.action.args.get("timeout_seconds"))
    cwd = context.cwd
    process: subprocess.Popen | None = None
    try:
        cwd = _resolve_cwd(action, context, sandbox)
        denial = _policy_denial(argv, allowed_commands)
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
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **process_group_kwargs(),
        )
        stdout, stderr, stop_reason = _communicate(process, timeout_seconds, control)
        if stop_reason is not None:
            tree_stop_error = _stop_process_tree(process)
            stdout, stderr, output_error = _collect_stopped_output(process, stdout, stderr)
            return _stopped_observation(
                action,
                context,
                observation_index=observation_index,
                argv=argv,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                stop_reason=stop_reason,
                stdout=stdout,
                stderr=stderr,
                tree_stop_error=tree_stop_error or output_error,
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
    except KeyboardInterrupt:
        if process is not None:
            _stop_process_tree(process)
            _collect_stopped_output(process, b"", b"")
        raise
    except OSError as exc:
        tree_stop_error = _stop_process_tree(process) if process is not None else None
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=str(exc),
            details={
                "argv": argv,
                "cwd": str(cwd),
                **({"tree_stop_error": tree_stop_error} if tree_stop_error else {}),
            },
        )

    assert process is not None
    stdout, stdout_truncated = _truncate(_decode_output(stdout), context.budget.command_output_chars)
    stderr, stderr_truncated = _truncate(_decode_output(stderr), context.budget.command_output_chars)
    data = {
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Command exited with code {process.returncode}.",
        data=data,
    )


def _communicate(
    process: subprocess.Popen,
    timeout_seconds: int,
    control: RunControl | None,
) -> tuple[bytes, bytes, StopReason | str | None]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if process.poll() is not None:
            return (*process.communicate(), None)
        stop_reason = None if control is None else control.stop_reason()
        if stop_reason is not None:
            if process.poll() is not None:
                continue
            return b"", b"", stop_reason
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if process.poll() is not None:
                continue
            return b"", b"", "tool_timeout"
        try:
            stdout, stderr = process.communicate(timeout=min(PROCESS_POLL_SECONDS, remaining))
            return stdout, stderr, None
        except subprocess.TimeoutExpired:
            continue


def _stop_process_tree(process: subprocess.Popen) -> str | None:
    return stop_process_tree(process)


def process_group_kwargs() -> dict[str, bool | int]:
    return (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )


def stop_process_tree(process: subprocess.Popen) -> str | None:
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=PROCESS_STOP_SECONDS,
            )
            if completed.returncode != 0:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=PROCESS_STOP_SECONDS)
                return f"taskkill failed with code {completed.returncode}: {_decode_output(completed.stderr).strip()}"
            return None

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return None
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.wait(timeout=PROCESS_STOP_SECONDS)
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            process.kill()
            process.wait(timeout=PROCESS_STOP_SECONDS)
        except (OSError, subprocess.SubprocessError):
            pass
        return str(exc)


def _collect_stopped_output(
    process: subprocess.Popen,
    stdout: bytes,
    stderr: bytes,
) -> tuple[bytes, bytes, str | None]:
    try:
        return (*process.communicate(timeout=PROCESS_STOP_SECONDS), None)
    except subprocess.TimeoutExpired as exc:
        if process.poll() is None:
            process.kill()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        return exc.stdout or stdout, exc.stderr or stderr, "process output pipes did not close after tree stop"


def _stopped_observation(
    action: InternalAction,
    context: RunContext,
    *,
    observation_index: int,
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
    stop_reason: StopReason | str,
    stdout: bytes,
    stderr: bytes,
    tree_stop_error: str | None,
) -> Observation:
    stdout_text = _truncate(_decode_output(stdout), context.budget.command_output_chars)[0]
    stderr_text = _truncate(_decode_output(stderr), context.budget.command_output_chars)[0]
    details = {
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }
    if stop_reason == "cancelled":
        code = ErrorCode.CANCELLED
        message = "Run cancelled while command was running."
        details["stop_reason"] = "cancelled"
    elif stop_reason == "timed_out":
        code = ErrorCode.TIMEOUT
        message = "Run timed out while command was running."
        details.update(stop_reason="timed_out", timeout_source="run_timeout")
    else:
        code = ErrorCode.TIMEOUT
        message = "Command timed out."
        details["timeout_source"] = "tool_timeout"
    if tree_stop_error:
        details["tree_stop_error"] = tree_stop_error
    return make_error_observation(
        action.action_id,
        context.run_id,
        observation_index=observation_index,
        code=code,
        message=message,
        details=details,
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


def _policy_denial(argv: list[str], allowed_commands: tuple[str, ...] = ()) -> str | None:
    return command_policy_denial(argv, allowed_commands)


def command_policy_denial(argv: list[str], allowed_commands: tuple[str, ...] = ()) -> str | None:
    executable = _executable_name(argv[0])
    if executable in SHELL_WRAPPERS:
        return "Shell wrapper commands are not supported."
    if executable in NETWORK_COMMANDS:
        return "Network commands are disabled by policy."
    if executable in DANGEROUS_COMMANDS:
        return "Dangerous commands are denied by policy."
    if _matches_allowed_command(argv, allowed_commands):
        return None
    if executable in {"git", "git.exe"}:
        return _git_policy_denial(argv)
    if executable in PYTHON_COMMANDS:
        return _python_policy_denial(argv)
    if executable in {"pytest", "pytest.exe", "rg", "rg.exe"}:
        return None
    return "Command is not allowed by default."


def _matches_allowed_command(argv: list[str], allowed_commands: tuple[str, ...]) -> bool:
    for command in allowed_commands:
        # ponytail: whitespace splitting cannot express one argv token containing spaces; use token arrays if needed.
        prefix = command.split()
        if not prefix or len(prefix) > len(argv):
            continue
        if (
            _normalized_executable(argv[0]) == _normalized_executable(prefix[0])
            and argv[1 : len(prefix)] == prefix[1:]
        ):
            return True
    return False


def _normalized_executable(executable: str) -> str:
    return _executable_name(executable).removesuffix(".exe")


def _validate_path_arguments(argv: list[str], sandbox: WorkspaceSandbox) -> None:
    validate_command_paths(argv, sandbox)


def validate_command_paths(argv: list[str], sandbox: WorkspaceSandbox) -> None:
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
