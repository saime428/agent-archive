import errno
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agent.cli import app
from agent.config import AgentConfig
from agent.core.chat import ConversationState
from agent.llm.deepseek import DeepSeekError
from agent.llm.fake import FakeLLMClient


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
    assert "deepseek api key env:" in result.output
    assert "deepseek api key present:" in result.output
    assert "config sandbox:" in result.output
    assert "config approval:" in result.output
    assert "config web_search_enabled:" in result.output
    assert "document dependency pypdf:" in result.output
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
    assert "deepseek api key env:" in result.output
    assert "deepseek api key present:" in result.output
    assert "config sandbox:" in result.output
    assert "config approval:" in result.output
    assert "config web_search_enabled:" in result.output
    assert "document dependency pypdf:" in result.output
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
    assert "route completion: 100%" in result.output
    assert "startup command: agent start" in result.output
    assert "config readable: true" in result.output
    assert "provider: fake" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "settings writes: read-only" in result.output
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


def test_start_agent_launcher_points_at_workbench() -> None:
    launcher = Path(__file__).resolve().parents[1] / "start-agent.cmd"
    script = launcher.read_text(encoding="utf-8")

    assert 'cd /d "%~dp0"' in script
    assert 'set "PYTHONPATH=src"' in script
    assert 'set "AGENT_PORT=8000"' in script
    assert "AGENT_PORT_END=%AGENT_PORT%+19" in script
    assert 'set "AGENT_LOG=%~dp0.agent\\start-agent.log"' in script
    assert "netstat -ano" in script
    assert ":found_port" in script
    assert "http://127.0.0.1:%AGENT_PORT%/" in script
    assert 'python -m agent.cli start --cwd "%CD%" --port %AGENT_PORT% >> "%AGENT_LOG%" 2>&1' in script
    assert "Agent Workbench exited with code %AGENT_EXIT%." in script
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
    monkeypatch.setattr("agent.cli.smoke_deepseek_provider", fake_smoke)

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
    monkeypatch.setattr("agent.cli.smoke_deepseek_provider", fake_smoke)

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
    monkeypatch.setattr("agent.cli.smoke_deepseek_provider", fake_smoke)

    result = runner.invoke(app, ["provider", "smoke", "deepseek", "--cwd", str(workspace)])

    assert result.exit_code == 1
    assert "DeepSeek API key is required in DEEPSEEK_API_KEY" in result.output
    assert calls == []


def test_provider_smoke_rejects_unknown_provider() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["provider", "smoke", "fake"])

    assert result.exit_code == 1
    assert "Unsupported provider smoke target: fake" in result.output


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
    assert "provider: fake" in result.output
    assert "model: deepseek-v4-flash" in result.output
    assert "deepseek_api_key_env: DEEPSEEK_API_KEY" in result.output
    assert f"cwd: {workspace.resolve()}" in result.output
    assert "loaded files: none" in result.output


def test_config_show_outputs_project_config_and_warning(tmp_path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('mode = "auto"\nsurprise = true\n', encoding="utf-8")

    result = runner.invoke(app, ["config", "show", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "mode: auto" in result.output
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
