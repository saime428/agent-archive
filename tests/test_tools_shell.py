from __future__ import annotations

import sys

from agent.core.actions import ErrorCode, parse_model_action
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.shell import execute_run_command


def _parse_run_command(context: RunContext, args: dict):
    return parse_model_action(
        {
            "message": "Run command.",
            "action": {"name": "run_command", "args": args},
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )


def test_run_command_executes_structured_argv(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "print('hello')"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["exit_code"] == 0
    assert observation.data["stdout"] == "hello\n"
    assert observation.data["stderr"] == ""
    assert observation.data["stdout_truncated"] is False
    assert observation.data["stderr_truncated"] is False


def test_run_command_uses_workspace_relative_cwd(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "import os; print(os.path.basename(os.getcwd()))"],
            "cwd": "nested",
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["cwd"] == str((tmp_path / "nested").resolve())
    assert observation.data["stdout"] == "nested\n"


def test_run_command_rejects_cwd_escape(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "print('nope')"],
            "cwd": "../",
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


def test_run_command_rejects_path_argument_escape(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": ["pytest", "../outside"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


def test_run_command_rejects_protected_internal_path_argument(tmp_path) -> None:
    protected = tmp_path / ".agent" / "runs" / "run_1"
    protected.mkdir(parents=True)
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": ["pytest", ".agent/runs/run_1"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


def test_run_command_rejects_shell_wrapper(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": ["powershell", "-Command", "Write-Host hi"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.POLICY_DENIED


def test_run_command_rejects_network_command(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": ["curl", "https://example.com"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.POLICY_DENIED


def test_run_command_times_out(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(2)"],
            "cwd": None,
            "timeout_seconds": 1,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TIMEOUT


def test_run_command_truncates_large_output(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "print('x' * 25000)"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["stdout_truncated"] is True
    assert observation.data["stdout"].endswith("\n[truncated]")
