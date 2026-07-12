from __future__ import annotations

import sys

from agent.core.actions import ErrorCode, parse_model_action
from agent.core.budget import ContextBudget
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.shell import _policy_denial, execute_run_command


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


def test_run_command_accepts_external_path_argument_when_computer_read_enabled(tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("external", encoding="utf-8")
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [
                sys.executable,
                "-c",
                "import pathlib; print(pathlib.Path('payload').name)",
                str(outside),
            ],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(
        action,
        context,
        WorkspaceSandbox(tmp_path, allow_external_read=True),
        observation_index=1,
    )

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["stdout"] == "payload\n"


def test_run_command_resolves_external_cwd_when_computer_read_enabled(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    external_file = external / "marker.txt"
    external_file.write_text("ok", encoding="utf-8")
    context = RunContext.create("run", cwd=workspace, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "import os; print(os.path.basename(os.getcwd()))"],
            "cwd": str(external),
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(
        action,
        context,
        WorkspaceSandbox(workspace, allow_external_read=True),
        observation_index=1,
    )

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["cwd"] == str(external.resolve())
    assert observation.data["stdout"] == "external\n"
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


def test_command_policy_denies_python_script_without_allowlist() -> None:
    assert _policy_denial(["python", "script.py"]) == (
        "Only Python one-liners and pytest module runs are allowed by default."
    )


def test_command_policy_matches_allowed_token_prefixes() -> None:
    assert _policy_denial([r"C:\Python313\PYTHON.EXE", "script.py"], ("python",)) is None
    assert _policy_denial(["pip", "show", "pydantic"], ("pip show",)) is None
    assert _policy_denial(["pip", "Show", "pydantic"], ("pip show",)) == "Command is not allowed by default."
    assert _policy_denial(["pip", "install", "pydantic"], ("pip show",)) == "Command is not allowed by default."
    assert _policy_denial(["npm", "testing"], ("npm test",)) == "Command is not allowed by default."
    assert _policy_denial(["git", "commit", "-m", "message"]) == (
        "Only read-only git commands are allowed by default."
    )
    assert _policy_denial(["git", "commit", "-m", "message"], ("git commit",)) is None


def test_command_policy_hard_denials_override_allowlist() -> None:
    assert _policy_denial(["powershell", "-Command", "echo hi"], ("powershell",)) == (
        "Shell wrapper commands are not supported."
    )
    assert _policy_denial(["curl", "https://example.com"], ("curl",)) == (
        "Network commands are disabled by policy."
    )
    assert _policy_denial(["rm", "notes.txt"], ("rm",)) == "Dangerous commands are denied by policy."


def test_run_command_executes_allowlisted_python_script(tmp_path) -> None:
    (tmp_path / "script.py").write_text("print('allowed')\n", encoding="utf-8")
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "script.py"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(
        action,
        context,
        WorkspaceSandbox(tmp_path),
        observation_index=1,
        allowed_commands=("python",),
    )

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["stdout"] == "allowed\n"


def test_run_command_allowlist_does_not_bypass_path_sandbox(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "../outside.py"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(
        action,
        context,
        WorkspaceSandbox(tmp_path),
        observation_index=1,
        allowed_commands=("python",),
    )

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


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


def test_run_command_uses_context_budget_for_output(tmp_path) -> None:
    context = RunContext.create(
        "run",
        cwd=tmp_path,
        run_id="run_shell",
        budget=ContextBudget(command_output_chars=5),
    )
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "print('abcdefghij')"],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["stdout"] == "abcde\n[truncated]"
    assert observation.data["stdout_truncated"] is True
