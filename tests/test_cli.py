import errno
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agent.cli import app
from agent.config import AgentConfig
from agent.core.automation import AutomationStore
from agent.core.chat import ConversationState
from agent.core.memory import MemoryStore
from agent.core.run_control import RunControl
from agent.core.run_lease import WorkspaceRunLease
from agent.llm.deepseek import DeepSeekError
from agent.llm.fake import FakeLLMClient
from agent.mcp_runtime import McpRuntimeError, McpStdioRuntime

_MCP_FIXTURE = (Path(__file__).parent / "fixtures" / "mcp_stdio_server.py").resolve()


def _install_recording_mcp_runtime(monkeypatch, *, discovery_error=None, close_error=None):
    instances = []

    class RecordingRuntime:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace
            self.discover_calls = 0
            self.close_calls = 0
            instances.append(self)

        def discover_tools(self) -> tuple:
            self.discover_calls += 1
            if discovery_error is not None:
                raise discovery_error
            return ()

        def close(self) -> None:
            self.close_calls += 1
            if close_error is not None:
                raise close_error

    monkeypatch.setattr("agent.cli.McpStdioRuntime", RecordingRuntime)
    return instances


def _install_probing_mcp_runtime(monkeypatch, *, after_discover=None):
    instances = []

    class ProbingRuntime(McpStdioRuntime):
        def __init__(self, workspace: Path) -> None:
            super().__init__(workspace)
            self.close_calls = 0
            instances.append(self)

        def discover_tools(self):
            result = super().discover_tools()
            if after_discover is not None:
                after_discover()
            return result

        def close(self) -> None:
            self.close_calls += 1
            super().close()

    monkeypatch.setattr("agent.cli.McpStdioRuntime", ProbingRuntime)
    return instances


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_exit(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} did not exit")


def _mcp_doctor_env(tmp_path, monkeypatch) -> Path:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return workspace


def _set_fixture_server(runner, workspace: Path, server_id: str, *extra_args: str, pass_env: tuple[str, ...] = ()) -> None:
    args = ["mcp", "set", server_id, "--command", str(Path(sys.executable).resolve()), f"--arg={_MCP_FIXTURE}"]
    for value in extra_args:
        args.append(f"--arg={value}")
    for name in pass_env:
        args.append(f"--pass-env={name}")
    args.extend(["--cwd", str(workspace)])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def test_doctor_reports_python_and_cwd() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Python" in result.output
    assert "cwd" in result.output
    assert "agent import: ok" in result.output
    assert "rg available:" in result.output
    assert "search backend:" in result.output
    assert "config mode:" in result.output
    assert "config provider:" in result.output
    assert "config model:" in result.output
    assert "config allowed_commands:" in result.output
    assert "provider adapter capabilities:" in result.output
    assert "deepseek api key env:" not in result.output
    assert "config sandbox:" in result.output
    assert "config approval:" in result.output
    assert "config web_search_enabled:" in result.output
    assert "document dependency pypdf:" in result.output
    assert "document dependency defusedxml:" in result.output
    assert "document dependency python-docx:" in result.output
    assert "document dependency openpyxl:" in result.output
    assert "document dependency python-pptx:" in result.output


def test_config_doctor_reports_same_core_diagnostics() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor"])

    assert result.exit_code == 0
    assert "Python" in result.output
    assert "cwd" in result.output
    assert "agent import: ok" in result.output
    assert "rg available:" in result.output
    assert "search backend:" in result.output
    assert "config mode:" in result.output
    assert "config provider:" in result.output
    assert "config model:" in result.output
    assert "config allowed_commands:" in result.output
    assert "provider adapter capabilities:" in result.output
    assert "deepseek api key env:" not in result.output
    assert "config sandbox:" in result.output
    assert "config approval:" in result.output
    assert "config web_search_enabled:" in result.output
    assert "document dependency pypdf:" in result.output
    assert "document dependency defusedxml:" in result.output
    assert "document dependency python-docx:" in result.output
    assert "document dependency openpyxl:" in result.output
    assert "document dependency python-pptx:" in result.output


def test_release_doctor_reports_release_readiness(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["release", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "release readiness: complete" in result.output
    assert "route completion: 100% (legacy local baseline)" in result.output
    assert "startup command: agent start" in result.output
    assert "config readable: true" in result.output
    assert "provider: fake" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "provider adapter capabilities: streaming=false native_tools=false" in result.output
    assert "deepseek api key present:" not in result.output
    assert "settings writes: controlled allowlist (no secrets/approval bypass)" in result.output
    assert "packaging: deferred (not required for local release)" in result.output
    assert "test command: python -m pytest -q" in result.output


def test_run_reports_fake_llm_result(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 0
    assert "inspect project" in result.output
    assert "run_id:" in result.output
    assert "status: ok" in result.output
    assert "completed: true" in result.output
    assert "terminal_reason: done" in result.output
    assert "final:" in result.output
    assert "summary:" in result.output


def test_run_and_chat_validate_timeout_options() -> None:
    runner = CliRunner()

    run_help = runner.invoke(app, ["run", "--help"])
    chat_help = runner.invoke(app, ["chat", "--help"])
    run_invalid = runner.invoke(app, ["run", "--timeout-seconds", "0", "inspect project"])
    chat_invalid = runner.invoke(app, ["chat", "--timeout-seconds", "3601"])

    assert run_help.exit_code == 0
    assert chat_help.exit_code == 0
    assert "--timeout-seconds" in run_help.output
    assert "--timeout-seconds" in chat_help.output
    assert run_invalid.exit_code == 2
    assert chat_invalid.exit_code == 2


def test_run_timeout_stops_before_model_call_and_releases_workspace(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    control = RunControl(deadline=0, clock=lambda: 0)

    class NoCallLLM(FakeLLMClient):
        def chat(self, *_args, **_kwargs):
            raise AssertionError("model must not be called after the run deadline")

    monkeypatch.setattr("agent.cli.RunControl.with_timeout", lambda _seconds: control)
    monkeypatch.setattr("agent.cli._make_llm", lambda _config: NoCallLLM())

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "terminal_reason: timed_out" in result.output
    assert "error: TIMEOUT: Run timed out." in result.output
    with WorkspaceRunLease.acquire(workspace, owner={"kind": "test"}):
        pass


def test_run_rejects_busy_workspace_before_creating_model(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model_created = False

    def make_model(_config):
        nonlocal model_created
        model_created = True
        return FakeLLMClient()

    monkeypatch.setattr("agent.cli._make_llm", make_model)
    with WorkspaceRunLease.acquire(workspace, owner={"kind": "test"}):
        result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "Workspace already has an active Agent turn." in result.output
    assert model_created is False


def test_run_owns_and_closes_one_mcp_runtime(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = _install_recording_mcp_runtime(monkeypatch)

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 0
    assert len(instances) == 1
    assert instances[0].workspace == workspace.resolve()
    assert instances[0].discover_calls == 1
    assert instances[0].close_calls == 1


def test_run_can_approve_and_execute_confirmation_required_action(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {
                        "path": "notes.txt",
                        "content": "approved\n",
                        "create_parents": False,
                    },
                },
            },
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {
                        "final": "Wrote notes.",
                        "changed_files": ["notes.txt"],
                        "next_steps": [],
                    },
                },
            },
        ]
    )
    monkeypatch.setattr("agent.cli._make_llm", lambda _config: llm)

    result = runner.invoke(
        app,
        ["run", "--cwd", str(workspace), "write notes"],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "activity: waiting for approval write_file" in result.output
    assert "approval required: write_file" in result.output
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "approved\n"


def test_run_closes_mcp_runtime_after_provider_failure(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = _install_recording_mcp_runtime(monkeypatch)

    def fail_provider(_config):
        raise DeepSeekError("provider failed safely")

    monkeypatch.setattr("agent.cli._make_llm", fail_provider)
    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "provider failed safely" in result.output
    assert "Traceback" not in result.output
    assert len(instances) == 1
    assert instances[0].discover_calls == 0
    assert instances[0].close_calls == 1


def test_run_closes_mcp_runtime_after_keyboard_interrupt(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = _install_recording_mcp_runtime(monkeypatch)
    monkeypatch.setattr("agent.cli._make_llm", lambda _config: object())

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("agent.cli.run_once", interrupt)
    result = runner.invoke(
        app,
        ["run", "--cwd", str(workspace), "inspect project"],
    )

    assert result.exit_code != 0
    assert len(instances) == 1
    assert instances[0].close_calls == 1


def test_run_maps_mcp_discovery_error_and_closes_without_traceback(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    error = McpRuntimeError(stage="discovery", server_id="local", message="safe discovery failure")
    instances = _install_recording_mcp_runtime(monkeypatch, discovery_error=error)

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "MCP discovery failed for server 'local': safe discovery failure" in result.output
    assert "Traceback" not in result.output
    assert len(instances) == 1
    assert instances[0].close_calls == 1


def test_chat_reuses_one_mcp_runtime_across_turns_and_closes_on_exit(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = _install_recording_mcp_runtime(monkeypatch)

    result = runner.invoke(
        app,
        ["chat", "--cwd", str(workspace)],
        input="first\nsecond\n/exit\n",
    )

    assert result.exit_code == 0
    assert "turn: 2" in result.output
    assert len(instances) == 1
    assert instances[0].discover_calls == 2
    assert instances[0].close_calls == 1


def test_chat_timeout_persists_turn_and_continues(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    controls = iter([RunControl(deadline=0, clock=lambda: 0), RunControl()])
    monkeypatch.setattr("agent.cli.RunControl.with_timeout", lambda _seconds: next(controls))

    result = runner.invoke(
        app,
        ["chat", "--cwd", str(workspace)],
        input="first\nsecond\n/exit\n",
    )

    assert result.exit_code == 0
    assert "terminal_reason: timed_out" in result.output
    assert "turn: 2" in result.output
    state = ConversationState.list(workspace)[0]
    assert [turn.terminal_reason for turn in state.turns] == ["timed_out", "done"]


def test_chat_execution_interrupt_persists_cancelled_turn_and_continues(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class InterruptOnceLLM(FakeLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return super().chat(messages, **kwargs)

    monkeypatch.setattr("agent.cli._make_llm", lambda _config: InterruptOnceLLM())

    result = runner.invoke(
        app,
        ["chat", "--cwd", str(workspace)],
        input="first\nsecond\n/exit\n",
    )

    assert result.exit_code == 0
    assert "terminal_reason: cancelled" in result.output
    assert "turn: 2" in result.output
    state = ConversationState.list(workspace)[0]
    assert [turn.terminal_reason for turn in state.turns] == ["cancelled", "done"]


def test_chat_closes_mcp_runtime_on_eof_and_ctrl_c(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    eof_instances = _install_recording_mcp_runtime(monkeypatch)
    eof_result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="")
    assert eof_result.exit_code == 0
    assert eof_instances[0].close_calls == 1

    interrupt_instances = _install_recording_mcp_runtime(monkeypatch)

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    interrupt_result = runner.invoke(app, ["chat", "--cwd", str(workspace)])
    assert interrupt_result.exit_code == 0
    assert interrupt_instances[0].close_calls == 1


def test_chat_maps_mcp_error_and_closes_without_traceback(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    error = McpRuntimeError(stage="config", server_id=None, message="safe config failure")
    instances = _install_recording_mcp_runtime(monkeypatch, discovery_error=error)

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="hello\n")

    assert result.exit_code == 1
    assert "MCP config failed: safe config failure" in result.output
    assert "Traceback" not in result.output
    assert instances[0].close_calls == 1


def test_chat_closes_mcp_runtime_after_provider_failure(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    instances = _install_recording_mcp_runtime(monkeypatch)

    def fail_provider(_config):
        raise DeepSeekError("chat provider failed safely")

    monkeypatch.setattr("agent.cli._make_llm", fail_provider)
    result = runner.invoke(app, ["chat", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "chat provider failed safely" in result.output
    assert "Traceback" not in result.output
    assert len(instances) == 1
    assert instances[0].discover_calls == 0
    assert instances[0].close_calls == 1


def test_ui_command_invokes_workbench_server(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(
        app,
        ["ui", "--cwd", str(workspace), "--host", "127.0.0.1", "--port", "8766"],
    )

    assert result.exit_code == 0
    assert calls[0]["workspace"] == workspace.resolve()
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8766


def test_start_command_is_workbench_start_alias(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(
        app,
        ["start", "--cwd", str(workspace), "--host", "127.0.0.1", "--port", "8767"],
    )

    assert result.exit_code == 0
    assert calls[0]["workspace"] == workspace.resolve()
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8767
    assert calls[0]["open_browser"] is False


def test_start_command_defaults_to_safe_workbench_port(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(app, ["start", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert calls[0]["port"] == 8000


def test_start_command_reports_non_loopback_host_without_retrying(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)
        raise ValueError("Agent Workbench host must be a loopback address.")

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(app, ["start", "--cwd", str(workspace), "--host", "0.0.0.0"])

    assert result.exit_code == 1
    assert "Agent Workbench host must be a loopback address." in result.output
    assert len(calls) == 1


def test_start_command_tries_next_port_when_requested_port_is_busy(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)
        if kwargs["port"] == 8765:
            raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(app, ["start", "--cwd", str(workspace), "--port", "8765"])

    assert result.exit_code == 0
    assert [call["port"] for call in calls] == [8765, 8766]
    assert "Port 8765 is busy; trying 8766." in result.output


def test_start_command_tries_next_port_when_windows_denies_bind(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)
        if kwargs["port"] == 8765:
            error = OSError("Access denied")
            error.winerror = 10013
            raise error

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(app, ["start", "--cwd", str(workspace), "--port", "8765"])

    assert result.exit_code == 0
    assert [call["port"] for call in calls] == [8765, 8766]


def test_start_command_scans_past_short_denied_port_block(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_serve_workbench(**kwargs):
        calls.append(kwargs)
        if kwargs["port"] < 8020:
            error = OSError("Access denied")
            error.winerror = 10013
            raise error

    monkeypatch.setattr("agent.cli.serve_workbench", fake_serve_workbench)

    result = runner.invoke(app, ["start", "--cwd", str(workspace), "--port", "8000"])

    assert result.exit_code == 0
    assert calls[0]["port"] == 8000
    assert calls[-1]["port"] == 8020


def test_start_agent_launcher_points_at_workbench() -> None:
    launcher = Path(__file__).resolve().parents[1] / "start-agent.cmd"
    script = launcher.read_text(encoding="utf-8")

    assert 'cd /d "%~dp0"' in script
    assert 'set "PYTHONPATH=src"' in script
    assert 'set "AGENT_PORT=8000"' in script
    assert 'set "AGENT_LOG=%~dp0.agent\\start-agent.log"' in script
    assert 'set "AGENT_PYTHON="' in script
    assert 'if exist "%~dp0.venv\\Scripts\\python.exe"' in script
    assert 'if not defined AGENT_PYTHON if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\\python.exe"' in script
    assert 'if not defined AGENT_PYTHON if exist "%USERPROFILE%\\miniconda3\\python.exe"' in script
    assert 'findstr /I /C:"\\Microsoft\\WindowsApps\\python.exe"' in script
    assert '"%AGENT_PYTHON%" -c "import agent.cli"' in script
    assert "netstat -ano" not in script
    assert ":found_port" not in script
    assert 'start ""' not in script
    assert '"%AGENT_PYTHON%" -m agent.cli start --cwd "%CD%" --port %AGENT_PORT% --open-browser >> "%AGENT_LOG%" 2>&1' in script
    assert 'python -m agent.cli start --cwd "%CD%" --port %AGENT_PORT%' not in script
    assert "Agent Workbench exited with code %AGENT_EXIT%." in script
    assert "Python exited with code %AGENT_EXIT%." in script
    assert "exit /b %AGENT_EXIT%" in script


def test_chat_runs_two_fake_turns_and_persists_session(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="first\nsecond\n")

    assert result.exit_code == 0
    assert "chat_id:" in result.output
    assert "turn: 1" in result.output
    assert "turn: 2" in result.output
    assert "status: ok" in result.output
    assert "completed: true" in result.output
    assert "terminal_reason: done" in result.output
    assert "final: FakeLLM received task: second" in result.output
    assert (workspace / ".agent" / "chats").exists()


def test_chat_exit_command_ends_without_running_turn(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class NoRunLLM:
        def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
            raise AssertionError("/exit should not call the model.")

    monkeypatch.setattr("agent.cli._make_llm", lambda config: NoRunLLM())

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="/exit\n")

    assert result.exit_code == 0
    assert "chat ended" in result.output
    assert not (workspace / ".agent" / "runs").exists()


def test_chat_help_command_prints_available_commands_without_running_turn(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class NoRunLLM:
        def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
            raise AssertionError("/help should not call the model.")

    monkeypatch.setattr("agent.cli._make_llm", lambda config: NoRunLLM())

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="/help\n/exit\n")

    assert result.exit_code == 0
    assert "commands:" in result.output
    assert "/exit" in result.output
    assert "/status" in result.output
    assert "/transcript" in result.output
    assert not (workspace / ".agent" / "runs").exists()


def test_chat_unknown_slash_command_is_local_error_without_running_turn(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class NoRunLLM:
        def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
            raise AssertionError("unknown slash command should not call the model.")

    monkeypatch.setattr("agent.cli._make_llm", lambda config: NoRunLLM())

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="/stauts\n/exit\n")

    assert result.exit_code == 0
    assert "unknown command: /stauts" in result.output
    assert "try /help" in result.output
    assert not (workspace / ".agent" / "runs").exists()


def test_chat_status_command_prints_current_session_state(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="first\n/status\n/exit\n")

    assert result.exit_code == 0
    assert "chat status:" in result.output
    assert "turns: 1" in result.output
    assert "last_status: ok" in result.output
    assert "last_terminal_reason: done" in result.output
    assert "last_final: FakeLLM received task: first" in result.output


def test_chat_transcript_command_prints_recent_turns(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="first\nsecond\n/transcript\n/exit\n")

    assert result.exit_code == 0
    assert "transcript:" in result.output
    assert "turn 1" in result.output
    assert "user: first" in result.output
    assert "final: FakeLLM received task: first" in result.output
    assert "turn 2" in result.output
    assert "user: second" in result.output
    assert "final: FakeLLM received task: second" in result.output


def test_chat_resume_uses_existing_session_id(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = ConversationState.create(workspace, session_id="chat_existing")
    state.add_turn(
        user="first",
        run_id="run_1",
        status="ok",
        completed=True,
        terminal_reason="done",
        final="first final",
        last_action="done",
        last_observation_summary="Done.",
    )
    state.save(AgentConfig())

    result = runner.invoke(app, ["chat", "--cwd", str(workspace), "--resume", "chat_existing"], input="second\n")

    assert result.exit_code == 0
    assert "chat_id: chat_existing" in result.output
    assert "turn: 2" in result.output
    assert "final: FakeLLM received task: second" in result.output


def test_chat_confirmed_approval_executes_write_action(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "notes.txt", "content": "hello\n", "create_parents": False},
                },
            },
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "Wrote notes.", "changed_files": ["notes.txt"], "next_steps": []},
                },
            },
        ]
    )
    monkeypatch.setattr("agent.cli._make_llm", lambda config: llm)

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="write notes\ny\n")

    assert result.exit_code == 0
    assert "approval required: write_file" in result.output
    assert "turn: 1" in result.output
    assert "final: Wrote notes." in result.output
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello\n"


def test_chat_prints_run_command_capability_warning_before_approval(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Run command.",
                "action": {
                    "name": "run_command",
                    "args": {
                        "argv": [sys.executable, "-c", "print('capability-warning-smoke')"],
                        "cwd": None,
                        "timeout_seconds": 5,
                    },
                },
            },
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "Command finished.", "changed_files": [], "next_steps": []},
                },
            },
        ]
    )
    monkeypatch.setattr("agent.cli._make_llm", lambda config: llm)

    result = runner.invoke(app, ["chat", "--cwd", str(workspace)], input="run command\ny\n")

    assert result.exit_code == 0
    assert result.output.index("Run commands execute local processes") < result.output.index("approve? [y/N]")
    assert "final: Command finished." in result.output


def test_chat_deepseek_uses_streaming_preview(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class StreamingLLM:
        def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
            raise AssertionError("chat() should not be used for deepseek chat streaming.")

        def stream_chat(self, messages: list[dict], *, temperature: float | None = None):
            yield '{"message":"Done.",'
            yield '"action":{"name":"done","args":{"final":"stream ok","changed_files":[],"next_steps":[]}}}'

    monkeypatch.setattr("agent.cli._make_llm", lambda config: StreamingLLM())

    result = runner.invoke(
        app,
        ["chat", "--cwd", str(workspace), "--provider", "deepseek", "--model", "deepseek-v4-flash"],
        input="finish\n",
    )

    assert result.exit_code == 0
    assert "raw model response preview:" in result.output
    assert '"message":"Done."' in result.output
    assert "final: stream ok" in result.output


def test_run_deepseek_keeps_non_streaming_path(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class StreamingCapableLLM:
        def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
            return {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "non-stream ok", "changed_files": [], "next_steps": []},
                },
            }

        def stream_chat(self, messages: list[dict], *, temperature: float | None = None):
            raise AssertionError("agent run should not use streaming.")

    monkeypatch.setattr("agent.cli._make_llm", lambda config: StreamingCapableLLM())

    result = runner.invoke(
        app,
        ["run", "--cwd", str(workspace), "--provider", "deepseek", "--model", "deepseek-v4-flash", "finish"],
    )

    assert result.exit_code == 0
    assert "raw model response preview:" not in result.output
    assert "final: non-stream ok" in result.output


def test_run_cwd_writes_run_under_requested_directory(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 0
    assert f"summary: {workspace}" in result.output
    assert (workspace / ".agent" / "runs").exists()


def test_run_accepts_config_cli_options(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(
        app,
        [
            "run",
            "--cwd",
            str(workspace),
            "--mode",
            "auto",
            "--sandbox",
            "workspace-write",
            "--approval",
            "risky-confirm",
            "--dry-run",
            "--provider",
            "fake",
            "--model",
            "deepseek-v4-pro",
            "inspect project",
        ],
    )

    assert result.exit_code == 0
    assert "mode: auto" in result.output
    assert "sandbox: workspace-write" in result.output
    assert "approval: risky-confirm" in result.output
    assert "dry_run: true" in result.output
    assert "provider: fake" in result.output
    assert "model: deepseek-v4-pro" in result.output
    summary_paths = list((workspace / ".agent" / "runs").glob("*/summary.md"))
    assert len(summary_paths) == 1
    summary = summary_paths[0].read_text(encoding="utf-8")
    assert "config_dry_run: true" in summary
    assert "config_provider: fake" in summary
    assert "config_model: deepseek-v4-pro" in summary


def test_run_no_dry_run_overrides_file_config(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("dry_run = true\n", encoding="utf-8")

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "--no-dry-run", "inspect project"])

    assert result.exit_code == 0
    assert "dry_run: false" in result.output


def test_run_approval_never_is_recorded_in_summary(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "--approval", "never", "inspect project"])

    assert result.exit_code == 0
    assert "approval: never" in result.output
    summary_paths = list((workspace / ".agent" / "runs").glob("*/summary.md"))
    assert len(summary_paths) == 1
    summary = summary_paths[0].read_text(encoding="utf-8")
    assert "config_approval: never" in summary


def test_run_and_chat_help_explain_approval_never_is_fail_closed() -> None:
    runner = CliRunner()

    run_help = runner.invoke(app, ["run", "--help"], terminal_width=200)
    chat_help = runner.invoke(app, ["chat", "--help"], terminal_width=200)

    assert run_help.exit_code == 0
    assert chat_help.exit_code == 0
    for output in (run_help.output, chat_help.output):
        rendered_text = " ".join(output.replace("│", " ").split())
        assert "never denies actions that would require confirmation" in rendered_text


def test_run_invalid_config_returns_nonzero(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('mode = "turbo"\n', encoding="utf-8")

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "Invalid value for mode" in result.output


def test_run_provider_error_returns_nonzero_without_traceback(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    monkeypatch.setattr("agent.cli._make_llm", lambda config: object())

    def fake_run_once(*args, **kwargs):
        raise DeepSeekError("DeepSeek model content was not a valid JSON action.")

    monkeypatch.setattr("agent.cli.run_once", fake_run_once)

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "--provider", "deepseek", "inspect project"])

    assert result.exit_code == 1
    assert "DeepSeek model content was not a valid JSON action." in result.output
    assert "Traceback" not in result.output


def test_run_error_result_prints_human_failure_summary(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    summary_path = workspace / ".agent" / "runs" / "run_error" / "summary.md"

    action = SimpleNamespace(action=SimpleNamespace(name="list_dir"))
    observation = SimpleNamespace(
        status="error",
        data=None,
        error=SimpleNamespace(code="TOOL_FAILED", message="Run stopped after reaching the iteration limit."),
    )
    result_obj = SimpleNamespace(
        context=SimpleNamespace(run_id="run_error"),
        action=action,
        observation=observation,
        skills=[],
        summary_path=summary_path,
    )

    monkeypatch.setattr("agent.cli._make_llm", lambda config: object())
    monkeypatch.setattr("agent.cli.run_once", lambda *args, **kwargs: result_obj)

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 1
    assert "run_id: run_error" in result.output
    assert "status: error" in result.output
    assert "completed: false" in result.output
    assert "terminal_reason: iteration_limit" in result.output
    assert "error: TOOL_FAILED: Run stopped after reaching the iteration limit." in result.output
    assert "runs show run_error" in result.output
    assert "Traceback" not in result.output


def test_tools_list_outputs_v01_tools_and_policy_categories() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["tools", "list"])

    assert result.exit_code == 0
    for tool_name in [
        "done",
        "ask_user",
        "list_dir",
        "read_file",
        "search_files",
        "write_file",
        "write_markdown_report",
        "apply_patch",
        "run_command",
        "git_status",
        "git_diff",
        "read_pdf",
        "read_docx",
        "read_xlsx",
        "read_pptx",
    ]:
        assert tool_name in result.output
    assert "read_file\tlow-risk" in result.output
    assert "git_diff\tlow-risk" in result.output
    assert "read_docx\tlow-risk" in result.output
    assert "read_xlsx\tlow-risk" in result.output
    assert "read_pptx\tlow-risk" in result.output
    assert "write_file\tconfirmation-required" in result.output
    assert "write_markdown_report\tconfirmation-required" in result.output
    assert "write_markdown_report\tconfirmation-required\tdry-run: skipped" in result.output
    assert "run_command\tconfirmation-required" in result.output
    assert "done\tterminal" in result.output
    assert "ask_user\tterminal" in result.output
    assert "dry-run: skipped" in result.output


def test_provider_smoke_deepseek_reports_success(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_smoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
            status="ok",
            action_name="done",
            final="smoke ok",
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)

    result = runner.invoke(
        app,
        ["provider", "smoke", "deepseek", "--cwd", str(workspace), "--model", "deepseek-v4-flash"],
    )

    assert result.exit_code == 0
    assert "provider: deepseek" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "api_key_env: DEEPSEEK_API_KEY" in result.output
    assert "status: ok" in result.output
    assert "action: done" in result.output
    assert "final: smoke ok" in result.output
    assert calls[0]["api_key"] == "secret"
    assert calls[0]["model"] == "deepseek-v4-flash"
    assert calls[0]["api_key_env"] == "DEEPSEEK_API_KEY"


def test_provider_smoke_deepseek_uses_workspace_secrets_env(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    secrets_path = workspace / ".agent" / "secrets.env"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text("DEEPSEEK_API_KEY=local-secret\n", encoding="utf-8")
    calls = []

    def fake_smoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
            status="ok",
            action_name="done",
            final="smoke ok",
        )

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)

    result = runner.invoke(app, ["provider", "smoke", "deepseek", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert calls[0]["api_key"] == "local-secret"
    assert "local-secret" not in result.output


def test_provider_smoke_deepseek_missing_key_returns_nonzero(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    def fake_smoke(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("should not be called")

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)

    result = runner.invoke(app, ["provider", "smoke", "deepseek", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "DeepSeek API key is required in DEEPSEEK_API_KEY" in result.output
    assert calls == []


def test_provider_smoke_rejects_unknown_provider() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["provider", "smoke", "fake"])

    assert result.exit_code == 1
    assert "Unsupported provider smoke target: fake" in result.output


def test_provider_smoke_openai_compat_requires_base_url(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "base_url" in result.output


def test_provider_smoke_openai_compat_calls_generic_smoke(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".agent"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "llama3"\n',
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_smoke(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            provider="openai-compat",
            model=kwargs["model"],
            api_key_env=kwargs["api_key_env"],
            status="ok",
            action_name="done",
            final="smoke ok",
        )

    monkeypatch.setattr("agent.llm.factory.smoke_provider", fake_smoke)

    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["provider_name"] == "openai-compat"
    assert "status: ok" in result.output


def test_provider_smoke_native_flag_calls_native_smoke(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "llama3"\n',
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_native_smoke(**kwargs):
        captured.update(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            provider="openai-compat", model=kwargs["model"], api_key_env=kwargs["api_key_env"],
            status="ok", action_name="done", final="smoke ok",
        )

    monkeypatch.setattr("agent.llm.factory.smoke_provider_native", fake_native_smoke)
    runner = CliRunner()

    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--native", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["provider_name"] == "openai-compat"
    assert "status: ok" in result.output


def test_skills_list_and_show_builtin_skill(tmp_path) -> None:
    runner = CliRunner()

    list_result = runner.invoke(app, ["skills", "list", "--cwd", str(tmp_path)])
    show_result = runner.invoke(app, ["skills", "show", "code-dev", "--cwd", str(tmp_path)])

    assert list_result.exit_code == 0
    assert "code-dev" in list_result.output
    assert "builtin" in list_result.output
    assert show_result.exit_code == 0
    assert "name: code-dev" in show_result.output
    assert "allowed_tools:" in show_result.output


def test_mcp_static_cli_lifecycle_never_starts_server(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    started = tmp_path / "started.txt"
    fixture = (Path(__file__).parent / "fixtures" / "mcp_stdio_server.py").resolve()
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()

    set_result = runner.invoke(
        app,
        [
            "mcp",
            "set",
            "fixture",
            "--command",
            str(Path(sys.executable).resolve()),
            "--arg",
            str(fixture),
            "--arg=--start-file",
            "--arg",
            str(started),
            "--server-cwd",
            "workspace",
            "--cwd",
            str(workspace),
        ],
    )
    list_result = runner.invoke(app, ["mcp", "list", "--cwd", str(workspace)])
    validate_result = runner.invoke(app, ["mcp", "validate", "fixture", "--cwd", str(workspace)])
    disable_result = runner.invoke(app, ["mcp", "disable", "fixture", "--cwd", str(workspace)])
    enable_result = runner.invoke(app, ["mcp", "enable", "fixture", "--cwd", str(workspace)])
    remove_result = runner.invoke(app, ["mcp", "remove", "fixture", "--cwd", str(workspace)])

    assert [result.exit_code for result in (set_result, list_result, validate_result, disable_result, enable_result, remove_result)] == [0] * 6
    assert "fixture\tmanaged\tenabled\tvalid" in set_result.output
    assert "fixture\tmanaged\tenabled\tvalid" in list_result.output
    assert "fixture\tmanaged\tenabled\tvalid" in validate_result.output
    assert "fixture\tmanaged\tdisabled\tdisabled" in disable_result.output
    assert "fixture\tmanaged\tenabled\tvalid" in enable_result.output
    assert "removed: fixture" in remove_result.output
    assert str(Path(sys.executable).resolve()) not in list_result.output
    assert str(fixture) not in list_result.output
    assert not started.exists()
    assert not (home / ".agent" / "mcp.d" / "fixture.toml").exists()


def test_mcp_cli_keeps_disabled_bad_command_recoverable(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()

    assert runner.invoke(
        app,
        ["mcp", "set", "broken", "--command", str(Path(sys.executable).resolve()), "--cwd", str(workspace)],
    ).exit_code == 0
    assert runner.invoke(app, ["mcp", "disable", "broken", "--cwd", str(workspace)]).exit_code == 0
    fragment = home / ".agent" / "mcp.d" / "broken.toml"
    fragment.write_text('command = "missing-command"\n', encoding="utf-8")

    listed = runner.invoke(app, ["mcp", "list", "--cwd", str(workspace)])
    validated = runner.invoke(app, ["mcp", "validate", "broken", "--cwd", str(workspace)])
    enabled = runner.invoke(app, ["mcp", "enable", "broken", "--cwd", str(workspace)])

    assert listed.exit_code == 0
    assert "broken\tmanaged\tdisabled\tdisabled" in listed.output
    assert validated.exit_code == 1
    assert enabled.exit_code == 1
    assert "sanitized PATH" in validated.output
    assert str(Path(sys.executable).resolve()) not in validated.output


def test_mcp_cli_bounds_static_validation_errors(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    manual = home / ".agent" / "mcp.toml"
    manual.parent.mkdir(parents=True)
    manual.write_text(
        "[servers.broken]\n" f"command = {json.dumps('x' * 2048)}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    result = CliRunner().invoke(app, ["mcp", "validate", "broken", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert len(result.output.rstrip("\n")) == 512
    assert result.output.endswith("...\n")


def test_mcp_cli_refuses_to_overwrite_or_remove_manual_server(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    manual = home / ".agent" / "mcp.toml"
    manual.parent.mkdir(parents=True)
    manual.write_text(
        "[servers.manual]\n" f"command = {json.dumps(str(Path(sys.executable).resolve()))}\n",
        encoding="utf-8",
    )
    original = manual.read_bytes()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()

    replaced = runner.invoke(
        app,
        ["mcp", "set", "manual", "--command", str(Path(sys.executable).resolve()), "--cwd", str(workspace)],
    )
    removed = runner.invoke(app, ["mcp", "remove", "manual", "--cwd", str(workspace)])

    assert replaced.exit_code == 1
    assert removed.exit_code == 1
    assert "manual" in replaced.output.lower()
    assert manual.read_bytes() == original


def test_mcp_doctor_reports_zero_enabled_servers_without_processes(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    started = tmp_path / "started.txt"
    instances = _install_probing_mcp_runtime(monkeypatch)
    runner = CliRunner()

    empty_result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])
    _set_fixture_server(runner, workspace, "fixture", "--start-file", str(started))
    assert runner.invoke(app, ["mcp", "disable", "fixture", "--cwd", str(workspace)]).exit_code == 0
    disabled_result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert empty_result.exit_code == 0
    assert "enabled servers: 0" in empty_result.output
    assert disabled_result.exit_code == 0
    assert "enabled servers: 0" in disabled_result.output
    assert "fixture\tmanaged\tdisabled\tdisabled" in disabled_result.output
    assert instances == []
    assert not started.exists()


def test_mcp_doctor_probes_enabled_fixture_with_one_runtime(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    started = tmp_path / "started.txt"
    instances = _install_probing_mcp_runtime(monkeypatch)
    runner = CliRunner()
    _set_fixture_server(runner, workspace, "fixture", "--start-file", str(started))

    result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0, result.output
    assert "enabled servers: 1" in result.output
    assert "fixture\tready\t1 tools" in result.output
    pids = [int(line) for line in started.read_text(encoding="ascii").splitlines()]
    assert len(pids) == 1
    _wait_for_pid_exit(pids[0])
    assert len(instances) == 1
    assert instances[0].close_calls == 1


def test_mcp_doctor_reports_bounded_initialize_failure_without_secrets(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    started = tmp_path / "started.txt"
    monkeypatch.setenv("MCP_DOCTOR_SECRET", "doctor-secret-value")
    runner = CliRunner()
    _set_fixture_server(
        runner,
        workspace,
        "fixture",
        "--mode",
        "crash",
        "--start-file",
        str(started),
        pass_env=("MCP_DOCTOR_SECRET",),
    )

    result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "MCP" in result.output
    assert "fixture" in result.output
    assert "doctor-secret-value" not in result.output
    assert "Traceback" not in result.output
    for line in result.output.splitlines():
        assert len(line) <= 512
    for line in started.read_text(encoding="ascii").splitlines():
        _wait_for_pid_exit(int(line))


def test_mcp_doctor_fails_closed_on_config_error_before_processes(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    home = Path(os.environ["USERPROFILE"] if os.name == "nt" else os.environ["HOME"])
    manual = home / ".agent" / "mcp.toml"
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_text('[servers.broken]\ncommand = "missing-command"\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "MCP" in result.output
    assert "broken" in result.output
    assert "Traceback" not in result.output


def test_mcp_doctor_skips_disabled_bad_command_and_probes_enabled(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    home = Path(os.environ["USERPROFILE"] if os.name == "nt" else os.environ["HOME"])
    started = tmp_path / "started.txt"
    runner = CliRunner()
    _set_fixture_server(runner, workspace, "fixture", "--start-file", str(started))
    _set_fixture_server(runner, workspace, "broken")
    assert runner.invoke(app, ["mcp", "disable", "broken", "--cwd", str(workspace)]).exit_code == 0
    (home / ".agent" / "mcp.d" / "broken.toml").write_text('command = "missing-command"\n', encoding="utf-8")

    result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0, result.output
    assert "broken\tmanaged\tdisabled\tdisabled" in result.output
    assert "fixture\tready\t1 tools" in result.output
    pids = [int(line) for line in started.read_text(encoding="ascii").splitlines()]
    assert len(pids) == 1
    _wait_for_pid_exit(pids[0])


def test_mcp_doctor_closes_runtime_after_keyboard_interrupt(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    started = tmp_path / "started.txt"

    def interrupt() -> None:
        raise KeyboardInterrupt()

    instances = _install_probing_mcp_runtime(monkeypatch, after_discover=interrupt)
    runner = CliRunner()
    _set_fixture_server(runner, workspace, "fixture", "--start-file", str(started))

    result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code != 0
    assert len(instances) == 1
    assert instances[0].close_calls == 1
    pids = [int(line) for line in started.read_text(encoding="ascii").splitlines()]
    assert len(pids) == 1
    _wait_for_pid_exit(pids[0])


def test_mcp_doctor_close_failure_keeps_first_diagnostic_and_nonzero(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()
    _set_fixture_server(runner, workspace, "fixture")

    discovery_error = McpRuntimeError(stage="discovery", server_id="fixture", message="Discovery diagnostic wins.")
    close_error = McpRuntimeError(stage="runtime", server_id=None, message="Close cleanup failed.")
    _install_recording_mcp_runtime(monkeypatch, discovery_error=discovery_error, close_error=close_error)
    both_result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    _install_recording_mcp_runtime(monkeypatch, close_error=close_error)
    close_only_result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert both_result.exit_code == 1
    assert "Discovery diagnostic wins." in both_result.output
    assert "Close cleanup failed." not in both_result.output
    assert close_only_result.exit_code == 1
    assert "Close cleanup failed." in close_only_result.output


def test_mcp_doctor_reports_state_only_orphan_without_processes(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    home = Path(os.environ["USERPROFILE"] if os.name == "nt" else os.environ["HOME"])
    instances = _install_probing_mcp_runtime(monkeypatch)
    runner = CliRunner()
    _set_fixture_server(runner, workspace, "ghost")
    assert runner.invoke(app, ["mcp", "disable", "ghost", "--cwd", str(workspace)]).exit_code == 0
    (home / ".agent" / "mcp.d" / "ghost.toml").unlink()

    result = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])
    assert runner.invoke(app, ["mcp", "remove", "ghost", "--cwd", str(workspace)]).exit_code == 0
    cleaned = runner.invoke(app, ["mcp", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "ghost\torphan\tdisabled\torphan" in result.output
    assert "enabled servers: 0" in result.output
    assert cleaned.exit_code == 0
    assert "ghost" not in cleaned.output
    assert instances == []


_SKILL_FIXTURE = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-v1").resolve()


def test_skills_cli_runs_the_install_disable_enable_remove_loop(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()

    validated = runner.invoke(app, ["skills", "validate", str(_SKILL_FIXTURE), "--cwd", str(workspace)])
    installed = runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)])
    listed = runner.invoke(app, ["skills", "list", "--cwd", str(workspace)])
    disabled = runner.invoke(app, ["skills", "disable", "reviewer", "--cwd", str(workspace)])
    shown_while_disabled = runner.invoke(app, ["skills", "show", "reviewer", "--cwd", str(workspace)])
    enabled = runner.invoke(app, ["skills", "enable", "reviewer", "--cwd", str(workspace)])
    removed = runner.invoke(app, ["skills", "remove", "reviewer", "--cwd", str(workspace)])
    listed_after = runner.invoke(app, ["skills", "list", "--cwd", str(workspace)])

    assert [result.exit_code for result in (validated, installed, listed, disabled, enabled, removed)] == [0] * 6
    assert "reviewer\tuser\tenabled\tvalid" in validated.output
    assert "reviewer\tuser\tenabled\tvalid" in installed.output
    assert "reviewer\tuser\tenabled\tvalid" in listed.output
    assert "code-dev\tbuiltin\tenabled\tvalid" in listed.output
    assert "reviewer\tuser\tdisabled\tdisabled" in disabled.output
    assert shown_while_disabled.exit_code == 1
    assert "disabled" in shown_while_disabled.output
    assert "reviewer\tuser\tenabled\tvalid" in enabled.output
    assert "removed: reviewer" in removed.output
    assert "reviewer" not in listed_after.output


def test_skills_list_never_prints_skill_bodies(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)]).exit_code == 0

    listed = runner.invoke(app, ["skills", "list", "--cwd", str(workspace)])
    shown = runner.invoke(app, ["skills", "show", "reviewer", "--cwd", str(workspace)])

    assert "REVIEWER-V1-BODY-MARKER" not in listed.output
    assert "REVIEWER-V1-BODY-MARKER" in shown.output


def test_skills_cli_refuses_to_remove_builtin_or_project_skills(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    project = workspace / ".agent" / "skills" / "planner" / "SKILL.md"
    project.parent.mkdir(parents=True)
    project.write_text(
        "---\nname: planner\ndescription: Project planner\nallowed_tools:\n  - read_file\n---\nPlan.\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    builtin = runner.invoke(app, ["skills", "remove", "code-dev", "--cwd", str(workspace)])
    project_removal = runner.invoke(app, ["skills", "remove", "planner", "--cwd", str(workspace)])

    assert builtin.exit_code == 1
    assert project_removal.exit_code == 1
    assert project.is_file()


def test_skills_install_reports_unsafe_candidate_without_traceback(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    result = CliRunner().invoke(app, ["skills", "install", str(candidate), "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "SKILL.md" in result.output
    assert "Traceback" not in result.output


def test_skills_show_unknown_skill_returns_nonzero(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["skills", "show", "missing", "--cwd", str(tmp_path)])

    assert result.exit_code == 1
    assert "Unknown skill: missing" in result.output


def test_memory_review_accept_list_and_undo(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("memory_auto_write = true\n", encoding="utf-8")

    run_result = runner.invoke(app, ["run", "--cwd", str(workspace), "remember parser tests"])
    assert run_result.exit_code == 0

    review_result = runner.invoke(app, ["memory", "review", "--cwd", str(workspace)])
    assert review_result.exit_code == 0
    assert "cand_" in review_result.output
    candidate_id = next(part for part in review_result.output.split() if part.startswith("cand_"))

    accept_result = runner.invoke(app, ["memory", "accept", candidate_id, "--cwd", str(workspace)])
    assert accept_result.exit_code == 0
    assert "accepted:" in accept_result.output
    entry_id = accept_result.output.split("accepted:", 1)[1].strip().split()[0]

    list_result = runner.invoke(app, ["memory", "list", "--cwd", str(workspace)])
    assert list_result.exit_code == 0
    assert entry_id in list_result.output

    undo_result = runner.invoke(app, ["memory", "undo", entry_id, "--cwd", str(workspace)])
    assert undo_result.exit_code == 0
    assert "undone:" in undo_result.output


def test_memory_reject_revise_delete_and_history_commands(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = MemoryStore(workspace)
    rejected_candidate = store.add_candidate(source_run_id="run_reject", source_excerpt="discard this")

    reject_result = runner.invoke(
        app,
        ["memory", "reject", rejected_candidate.candidate_id, "--cwd", str(workspace)],
    )

    assert reject_result.exit_code == 0
    assert f"rejected: {rejected_candidate.candidate_id}" in reject_result.output
    rejected_accept = runner.invoke(
        app,
        ["memory", "accept", rejected_candidate.candidate_id, "--cwd", str(workspace)],
    )
    assert rejected_accept.exit_code == 1
    assert "not pending" in rejected_accept.output
    assert "Traceback" not in rejected_accept.output

    accepted_candidate = store.add_candidate(source_run_id="run_accept", source_excerpt="old parser memory")
    accept_result = runner.invoke(
        app,
        ["memory", "accept", accepted_candidate.candidate_id, "--cwd", str(workspace)],
    )
    original_id = accept_result.output.split("accepted:", 1)[1].strip().split()[0]

    revise_result = runner.invoke(
        app,
        ["memory", "revise", original_id, "new parser memory", "--cwd", str(workspace)],
    )

    assert revise_result.exit_code == 0
    revised_id = revise_result.output.split("revised:", 1)[1].strip().split()[0]
    assert revise_result.output.splitlines() == [f"revised: {revised_id} supersedes: {original_id}"]
    list_result = runner.invoke(app, ["memory", "list", "--cwd", str(workspace)])
    assert revised_id in list_result.output
    assert original_id not in list_result.output

    history_result = runner.invoke(app, ["memory", "history", original_id, "--cwd", str(workspace)])
    assert history_result.exit_code == 0
    assert original_id in history_result.output
    assert revised_id in history_result.output
    assert "supersedes:" in history_result.output

    delete_result = runner.invoke(app, ["memory", "delete", revised_id, "--cwd", str(workspace)])
    assert delete_result.exit_code == 0
    assert f"deleted: {revised_id}" in delete_result.output
    assert len(delete_result.output.splitlines()) == 1
    assert runner.invoke(app, ["memory", "list", "--cwd", str(workspace)]).output == ""


def test_automation_add_enable_worker_and_audit_commands(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    added = runner.invoke(
        app,
        ["automation", "add", "inspect parser tests", "--every-minutes", "1", "--cwd", str(workspace)],
    )

    assert added.exit_code == 0
    automation_id = added.output.split("added:", 1)[1].strip().split()[0]
    assert automation_id.startswith("auto_")
    assert "status: disabled" in added.output
    listed = runner.invoke(app, ["automation", "list", "--cwd", str(workspace)])
    assert automation_id in listed.output
    assert "disabled" in listed.output

    enabled = runner.invoke(app, ["automation", "enable", automation_id, "--cwd", str(workspace)])
    assert enabled.exit_code == 0
    assert f"enabled: {automation_id}" in enabled.output

    worked = runner.invoke(app, ["automation", "worker", "--once", "--cwd", str(workspace)])
    assert worked.exit_code == 0
    assert "succeeded: 1" in worked.output

    attempts = runner.invoke(app, ["automation", "attempts", "--cwd", str(workspace)])
    assert attempts.exit_code == 0
    assert automation_id in attempts.output
    assert "status: succeeded" in attempts.output
    history = runner.invoke(app, ["automation", "history", automation_id, "--cwd", str(workspace)])
    assert history.exit_code == 0
    assert "disabled" in history.output
    assert "enabled" in history.output
    assert runner.invoke(app, ["automation", "notifications", "--cwd", str(workspace)]).output == ""

    disabled = runner.invoke(app, ["automation", "disable", automation_id, "--cwd", str(workspace)])
    assert disabled.exit_code == 0
    assert f"disabled: {automation_id}" in disabled.output


def test_automation_cancel_and_notifications_commands(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    store = AutomationStore(workspace)
    definition = store.add_definition(task="cancel me", interval_seconds=60, now=now)
    store.enable_definition(definition.automation_id, now=now)
    attempt = store.claim_due(now=now)[0]
    store.mark_running(attempt.attempt_id, now=now)

    cancelled = runner.invoke(app, ["automation", "cancel", attempt.attempt_id, "--cwd", str(workspace)])

    assert cancelled.exit_code == 0
    assert f"cancel_requested: {attempt.attempt_id}" in cancelled.output
    store.recover_incomplete(now=now + timedelta(seconds=1))
    notifications = runner.invoke(app, ["automation", "notifications", "--cwd", str(workspace)])
    assert notifications.exit_code == 0
    assert attempt.attempt_id in notifications.output
    assert "status: cancelled" in notifications.output


def test_automation_cli_keeps_task_and_error_on_one_line(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    store = AutomationStore(workspace)
    definition = store.add_definition(task="inspect\nparser", interval_seconds=60, now=now)
    store.enable_definition(definition.automation_id, now=now)
    attempt = store.claim_due(now=now)[0]
    store.finish_attempt(attempt.attempt_id, status="failed", error="first\nsecond", now=now)

    listed = runner.invoke(app, ["automation", "list", "--cwd", str(workspace)])
    notifications = runner.invoke(app, ["automation", "notifications", "--cwd", str(workspace)])

    assert listed.exit_code == 0
    assert listed.output.splitlines() == [
        f"{definition.automation_id}\tstatus: enabled\tevery_minutes: 1"
        "\ttimeout_seconds: 900\tskills: -\tinspect parser"
    ]
    assert notifications.exit_code == 0
    assert len(notifications.output.splitlines()) == 1
    assert "error: first second" in notifications.output


def test_config_show_outputs_defaults_for_requested_cwd(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mode: guided" in result.output
    assert "sandbox: workspace-write" in result.output
    assert "approval: risky-confirm" in result.output
    assert "dry_run: false" in result.output
    assert "web_search_enabled: false" in result.output
    assert "computer_read_enabled: false" in result.output
    assert "terminal_enabled: false" in result.output
    assert "provider: fake" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "allowed_commands: []" in result.output
    assert "provider adapter capabilities: streaming=false native_tools=false" in result.output
    assert f"cwd: {workspace.resolve()}" in result.output
    assert "loaded files: none" in result.output


def test_config_show_loads_workspace_secrets_before_reporting_key_presence(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".agent"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('provider = "deepseek"\n', encoding="utf-8")
    (config_dir / "secrets.env").write_text("DEEPSEEK_API_KEY=workspace-secret\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    runner = CliRunner()

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "api key required: true" in result.output
    assert "api key present: true" in result.output
    assert "workspace-secret" not in result.output


def test_config_show_marks_openai_compat_api_key_optional(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".agent"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "api key env: OPENAI_API_KEY" in result.output
    assert "api key required: false" in result.output
    assert "api key present: false" in result.output


def test_config_show_outputs_project_config_and_warning(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        'mode = "auto"\nallowed_commands = ["python", "pip show"]\nsurprise = true\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mode: auto" in result.output
    assert "allowed_commands: ['python', 'pip show']" in result.output
    assert f"loaded file: {config_path.resolve()}" in result.output
    assert "config warning: Ignoring unknown config key surprise" in result.output


def test_config_show_invalid_config_returns_nonzero(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('mode = "turbo"\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "Invalid value for mode" in result.output


def test_runs_list_reports_no_runs(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_runs_list_outputs_existing_run(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        run_dir = Path.cwd() / ".agent" / "runs" / "run_test"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.md").write_text("# Run run_test\n", encoding="utf-8")
        (run_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")
        result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0
    assert "run_test" in result.output


def test_runs_show_outputs_summary_snapshots_and_restore(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        run_dir = Path.cwd() / ".agent" / "runs" / "run_test"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.md").write_text("# Run run_test\n\n- final: ok\n", encoding="utf-8")
        (run_dir / "tool_calls.jsonl").write_text(
            '{"action":{"action":{"name":"write_file"}},"observation":{"status":"ok",'
            '"data":{"path":"notes.txt","snapshot_path":".agent/runs/run_test/snapshots/act/original",'
            '"restore_hint":"Restore by copying original back."}}}\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["runs", "show", "run_test"])

    assert result.exit_code == 0
    assert "Run run_test" in result.output
    assert "tool calls: 1" in result.output
    assert "snapshot" in result.output
    assert "Restore by copying" in result.output


def test_runs_show_missing_run_returns_nonzero(tmp_path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["runs", "show", "run_missing"])

    assert result.exit_code != 0
    assert "Run not found" in result.output


_SKILL_FIXTURE_V2 = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-v2").resolve()


def test_skills_cli_completes_the_update_and_package_round_trip(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()
    archive = tmp_path / "reviewer.skill.zip"
    assert runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)]).exit_code == 0

    updated = runner.invoke(
        app, ["skills", "update", "reviewer", str(_SKILL_FIXTURE_V2), "--cwd", str(workspace)]
    )
    shown = runner.invoke(app, ["skills", "show", "reviewer", "--cwd", str(workspace)])
    packaged = runner.invoke(
        app, ["skills", "package", "reviewer", "--output", str(archive), "--cwd", str(workspace)]
    )
    removed = runner.invoke(app, ["skills", "remove", "reviewer", "--cwd", str(workspace)])
    reinstalled = runner.invoke(app, ["skills", "install", str(archive), "--cwd", str(workspace)])
    shown_again = runner.invoke(app, ["skills", "show", "reviewer", "--cwd", str(workspace)])

    assert [result.exit_code for result in (updated, shown, packaged, removed, reinstalled, shown_again)] == [0] * 6
    assert "reviewer\tuser\tenabled\tvalid" in updated.output
    assert "revision:v2" in shown.output
    assert "packaged:" in packaged.output
    assert archive.is_file()
    assert "revision:v2" in shown_again.output


def test_skills_package_refuses_an_existing_output(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)]).exit_code == 0
    existing = tmp_path / "taken.skill.zip"
    existing.write_bytes(b"keep\n")

    result = runner.invoke(
        app, ["skills", "package", "reviewer", "--output", str(existing), "--cwd", str(workspace)]
    )

    assert result.exit_code == 1
    assert "exists" in result.output
    assert "Traceback" not in result.output
    assert existing.read_bytes() == b"keep\n"


def test_skills_update_rejects_a_mismatched_candidate_without_touching_the_target(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    home = Path(os.environ["USERPROFILE"] if os.name == "nt" else os.environ["HOME"])
    runner = CliRunner()
    assert runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)]).exit_code == 0
    installed = home / ".agent" / "skills" / "reviewer" / "SKILL.md"
    before = installed.read_bytes()
    invalid = Path(__file__).parent / "fixtures" / "skills" / "reviewer-invalid"

    result = runner.invoke(app, ["skills", "update", "reviewer", str(invalid), "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert installed.read_bytes() == before


def test_skills_doctor_reports_healthy_and_unhealthy_stores(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    runner = CliRunner()
    assert runner.invoke(app, ["skills", "install", str(_SKILL_FIXTURE), "--cwd", str(workspace)]).exit_code == 0

    healthy = runner.invoke(app, ["skills", "doctor", "--cwd", str(workspace)])

    assert healthy.exit_code == 0
    assert "skills healthy: true" in healthy.output
    assert "default skills: code-dev" in healthy.output
    assert "REVIEWER-V1-BODY-MARKER" not in healthy.output

    config = workspace / ".agent" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('default_skills = ["missing-skill"]\n', encoding="utf-8")
    unhealthy = runner.invoke(app, ["skills", "doctor", "--cwd", str(workspace)])

    assert unhealthy.exit_code == 1
    assert "skills healthy: false" in unhealthy.output
    assert "problem:" in unhealthy.output
    assert "missing-skill" in unhealthy.output


def test_skills_cli_never_renders_untrusted_content_as_markup(tmp_path, monkeypatch) -> None:
    workspace = _mcp_doctor_env(tmp_path, monkeypatch)
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    (hostile / "SKILL.md").write_text(
        "---\nname: hostile\ndescription: probe\nevil[/]tag: x\n---\nBody.\n", encoding="utf-8"
    )
    runner = CliRunner()

    rejected = runner.invoke(app, ["skills", "validate", str(hostile), "--cwd", str(workspace)])

    assert rejected.exit_code == 1
    assert rejected.exception is None or isinstance(rejected.exception, SystemExit)
    assert "[/]" in rejected.output
    assert "MarkupError" not in rejected.output

    body = tmp_path / "body"
    body.mkdir()
    (body / "SKILL.md").write_text(
        "---\nname: body\ndescription: probe\n---\nRAW [bold]not-markup[/bold] TAIL\n", encoding="utf-8"
    )
    assert runner.invoke(app, ["skills", "install", str(body), "--cwd", str(workspace)]).exit_code == 0
    shown = runner.invoke(app, ["skills", "show", "body", "--cwd", str(workspace)])

    assert shown.exit_code == 0
    assert "[bold]not-markup[/bold]" in shown.output


def test_doctor_shows_auth_env_for_deepseek_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text('provider = "deepseek"\n', encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "provider adapter capabilities: streaming=true native_tools=true" in result.output
    assert "api key env: DEEPSEEK_API_KEY" in result.output
    assert "api key required: true" in result.output
    assert "api key present: false" in result.output


def test_doctor_warns_on_native_tools_capability_mismatch(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert (
        "capability warning: native_tools enabled but provider lacks native tool calling"
        in result.output
    )


def test_run_prints_capability_warning_event(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 0
    assert "capability warning: native_tools unavailable; falling back to json-protocol" in result.output


def test_hooks_list_shows_builtins_and_state(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text(
        'enabled_hooks = ["audit"]\nblocking_hooks = ["audit"]\n', encoding="utf-8"
    )

    result = runner.invoke(app, ["hooks", "list", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "audit\tenabled\tblocking" in result.output
    assert "before_tool_format\tdisabled\t-" in result.output
    assert "fail\tdisabled\t-" in result.output


def test_hooks_list_marks_unknown_reference(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text('enabled_hooks = ["typo"]\n', encoding="utf-8")

    result = runner.invoke(app, ["hooks", "list", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "typo\tunknown\t-" in result.output


def test_config_show_lists_hook_keys(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "enabled_hooks: []" in result.output
    assert "blocking_hooks: []" in result.output


def test_doctor_lists_hook_keys(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "config enabled_hooks: []" in result.output
    assert "config blocking_hooks: []" in result.output


def test_mcp_show_prints_fields(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()
    assert runner.invoke(
        app,
        ["mcp", "set", "local", "--command", str(Path(sys.executable).resolve()), "--cwd", str(workspace)],
    ).exit_code == 0

    result = runner.invoke(app, ["mcp", "show", "local", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "server_id: local" in result.output
    assert "source: managed" in result.output
    assert "enabled: true" in result.output
    assert "status: valid" in result.output
    assert "command: " in result.output
    assert "args: " in result.output
    assert "pass_env: " in result.output
    assert "cwd: " in result.output


def test_mcp_show_unknown_exits_one(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()

    result = runner.invoke(app, ["mcp", "show", "missing", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "Server does not exist." in result.output


def test_doctor_reports_extension_summary_when_empty(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mcp servers: 0 total, 0 enabled, 0 invalid, 0 orphan" in result.output
    assert "skills: " in result.output
    assert "healthy=" in result.output


def test_doctor_counts_mcp_servers(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()
    assert runner.invoke(
        app,
        ["mcp", "set", "local", "--command", str(Path(sys.executable).resolve()), "--cwd", str(workspace)],
    ).exit_code == 0

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mcp servers: 1 total, 1 enabled, 0 invalid, 0 orphan" in result.output
    assert "mcp detail: agent mcp doctor" in result.output


def test_doctor_extension_summary_survives_store_error(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def broken_inventory(self):
        raise McpRuntimeError(stage="config", server_id=None, message="store unavailable")

    monkeypatch.setattr("agent.cli.McpConfigStore.inventory", broken_inventory)
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mcp inventory error: " in result.output


def test_config_set_scalar_roundtrip(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "set", "model", "my-model", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "saved: " in result.output
    shown = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])
    assert "model: my-model" in shown.output


def test_config_set_bool_and_int(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert runner.invoke(app, ["config", "set", "dry_run", "true", "--cwd", str(workspace)]).exit_code == 0
    assert runner.invoke(app, ["config", "set", "terminal_enabled", "true", "--cwd", str(workspace)]).exit_code == 0
    assert runner.invoke(app, ["config", "set", "memory_max_items", "9", "--cwd", str(workspace)]).exit_code == 0
    shown = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])
    assert "dry_run: true" in shown.output
    assert "terminal_enabled: true" in shown.output
    assert "memory_max_items: 9" in shown.output

    rejected = runner.invoke(app, ["config", "set", "dry_run", "yes", "--cwd", str(workspace)])
    assert rejected.exit_code == 1
    assert "expects true or false" in rejected.output


def test_config_set_list_key_takes_multiple_values(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "set", "default_skills", "a", "b", "--cwd", str(workspace)])

    assert result.exit_code == 0
    shown = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])
    assert "default_skills: ['a', 'b']" in shown.output


def test_config_set_scalar_rejects_multiple_values(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "set", "model", "a", "b", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "takes exactly one value" in result.output


def test_config_set_rejects_danger_values(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    sandbox = runner.invoke(app, ["config", "set", "sandbox", "danger-full-access", "--cwd", str(workspace)])
    approval = runner.invoke(app, ["config", "set", "approval", "never", "--cwd", str(workspace)])

    assert sandbox.exit_code == 1
    assert approval.exit_code == 1
    assert "edit the global config by hand" in sandbox.output
    assert "edit the global config by hand" in approval.output


def test_config_set_prints_new_warnings(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = runner.invoke(app, ["config", "set", "enabled_hooks", "typo", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "config warning: Unknown hook 'typo'" in result.output


def test_config_unset_falls_back(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert runner.invoke(app, ["config", "set", "model", "m2", "--cwd", str(workspace)]).exit_code == 0

    result = runner.invoke(app, ["config", "unset", "model", "--cwd", str(workspace)])

    assert result.exit_code == 0
    shown = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])
    assert "model: deepseek-v4-flash" in shown.output

    missing = runner.invoke(app, ["config", "unset", "model", "--cwd", str(workspace)])
    assert missing.exit_code == 1
    assert "Key is not set in project config" in missing.output
