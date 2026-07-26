from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from agent.core.actions import ErrorCode, parse_model_action
from agent.core.budget import ContextBudget
from agent.core.context import RunContext
from agent.core.run_control import RunControl
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools import shell as shell_tool
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


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                and code.value == 259
            )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


def _wait_for_pid_exit(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} did not exit")


def _read_pids(path: Path, *, timeout: float = 5.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return [int(value) for value in path.read_text(encoding="utf-8").splitlines()]
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for process ids in {path}")


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
            "argv": [sys.executable, "-c", "import time; print('before', flush=True); time.sleep(2)"],
            "cwd": None,
            "timeout_seconds": 1,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TIMEOUT
    assert observation.error.details is not None
    assert observation.error.details["timeout_source"] == "tool_timeout"
    assert observation.error.details["stdout"] == "before\n"


def test_run_command_surfaces_tree_stop_failure(monkeypatch, tmp_path) -> None:
    real_stop = shell_tool._stop_process_tree

    def stop_with_diagnostic(process) -> str:
        assert real_stop(process) is None
        return "forced tree-stop diagnostic"

    monkeypatch.setattr(shell_tool, "_stop_process_tree", stop_with_diagnostic)
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell_stop_error")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": None,
            "timeout_seconds": 1,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.error is not None
    assert observation.error.details is not None
    assert observation.error.details["tree_stop_error"] == "forced tree-stop diagnostic"


def test_run_command_keyboard_interrupt_stops_process(monkeypatch, tmp_path) -> None:
    real_stop = shell_tool._stop_process_tree
    stopped_pids: list[int] = []

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    def record_stop(process):
        stopped_pids.append(process.pid)
        return real_stop(process)

    monkeypatch.setattr(shell_tool, "_communicate", interrupt)
    monkeypatch.setattr(shell_tool, "_stop_process_tree", record_stop)
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell_interrupt")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": None,
            "timeout_seconds": 10,
        },
    )

    with pytest.raises(KeyboardInterrupt):
        execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert len(stopped_pids) == 1
    _wait_for_pid_exit(stopped_pids[0])


@pytest.mark.parametrize(
    ("stop_kind", "expected_code", "expected_reason", "expected_source"),
    [
        ("cancel", ErrorCode.CANCELLED, "cancelled", None),
        ("run_timeout", ErrorCode.TIMEOUT, "timed_out", "run_timeout"),
        ("tool_timeout", ErrorCode.TIMEOUT, None, "tool_timeout"),
    ],
)
def test_run_command_stop_terminates_parent_and_child_processes(
    tmp_path,
    stop_kind,
    expected_code,
    expected_reason,
    expected_source,
) -> None:
    pid_path = tmp_path / "tree-pids.txt"
    code = (
        "import os,pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()}\\n{child.pid}',encoding='utf-8');"
        "time.sleep(60)"
    )
    context = RunContext.create("run", cwd=tmp_path, run_id=f"run_shell_{stop_kind}")
    action = _parse_run_command(
        context,
        {
            "argv": [sys.executable, "-c", code, str(pid_path)],
            "cwd": None,
            "timeout_seconds": 1 if stop_kind == "tool_timeout" else 10,
        },
    )
    control = RunControl.with_timeout(1) if stop_kind == "run_timeout" else RunControl()
    cancel_thread = None
    pids: list[int] = []
    if stop_kind == "cancel":
        def cancel_after_start() -> None:
            pids.extend(_read_pids(pid_path))
            control.request_cancel()

        cancel_thread = threading.Thread(
            target=cancel_after_start,
            daemon=True,
        )
        cancel_thread.start()

    try:
        observation = execute_run_command(
            action,
            context,
            WorkspaceSandbox(tmp_path),
            observation_index=1,
            control=control if stop_kind != "tool_timeout" else None,
        )
        if cancel_thread is not None:
            cancel_thread.join(timeout=5)
            assert not cancel_thread.is_alive()
        if not pids:
            pids = _read_pids(pid_path)

        assert observation.status == "error"
        assert observation.error is not None
        assert observation.error.code == expected_code
        assert (observation.error.details or {}).get("stop_reason") == expected_reason
        assert (observation.error.details or {}).get("timeout_source") == expected_source
        assert "tree_stop_error" not in (observation.error.details or {})
        for pid in pids:
            _wait_for_pid_exit(pid)
    finally:
        if cancel_thread is not None:
            cancel_thread.join(timeout=5)
        for pid in pids:
            if _pid_exists(pid):
                _terminate_pid(pid)


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


def test_run_command_preserves_exit_stderr_and_replaces_invalid_utf8(tmp_path) -> None:
    context = RunContext.create("run", cwd=tmp_path, run_id="run_shell_output")
    action = _parse_run_command(
        context,
        {
            "argv": [
                sys.executable,
                "-c",
                "import os; os.write(1,b'out\\xff'); os.write(2,b'err\\r\\n'); raise SystemExit(7)",
            ],
            "cwd": None,
            "timeout_seconds": 5,
        },
    )

    observation = execute_run_command(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["exit_code"] == 7
    assert observation.data["stdout"] == "out�"
    assert observation.data["stderr"] == "err\n"


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
