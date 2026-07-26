from __future__ import annotations

from pathlib import Path

import pytest

import agent.tools.filesystem as filesystem_tools
from agent.config import AgentConfig
from agent.core.chat import ChatTurn, ConversationState
from agent.core.memory import MemoryStore
from agent.llm.fake import FakeLLMClient
from agent.web.chats import (
    build_chat_delete_payload,
    build_chat_payload,
    build_chat_rename_payload,
    build_chats_payload,
)
from agent.web.files import (
    build_diff_payload,
    build_file_payload,
    build_files_payload,
    build_restore_snapshot_payload,
    build_save_file_payload,
    build_search_payload,
)
from agent.web.runs import build_run_detail_payload, build_runs_payload
from agent.web.settings import (
    build_health_payload,
    build_config_payload,
    build_save_config_payload,
    build_tools_payload,
)


def _seed_chat(workspace: Path, session_id: str, messages: list[str]) -> ConversationState:
    state = ConversationState.create(workspace, session_id=session_id)
    state.turns = [
        ChatTurn(
            user=message,
            run_id=f"run_seed_{index}",
            status="ok",
            completed=True,
            terminal_reason="done",
            final=f"final {index}",
            last_action="done",
            last_observation_summary="Done.",
        )
        for index, message in enumerate(messages, start=1)
    ]
    state.save(AgentConfig())
    return state


def test_build_config_payload_reports_effective_workspace_config(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        'provider = "fake"\nmode = "auto"\nallowed_commands = ["python", "pip show"]\n',
        encoding="utf-8",
    )

    payload = build_config_payload(workspace)

    assert payload["workspace"] == str(workspace.resolve())
    assert payload["config"]["provider"] == "fake"
    assert payload["config"]["mode"] == "auto"
    assert payload["config"]["allowed_commands"] == ["python", "pip show"]
    assert str(config_path.resolve()) in payload["diagnostics"]["loaded_files"]


def test_build_save_config_payload_preserves_allowed_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('allowed_commands = ["python"]\ndry_run = false\n', encoding="utf-8")

    payload = build_save_config_payload(workspace, {"dry_run": True})

    config_text = config_path.read_text(encoding="utf-8")
    assert payload["config"]["allowed_commands"] == ["python"]
    assert 'allowed_commands = ["python"]' in config_text
    assert "dry_run = true" in config_text


def test_build_save_config_payload_writes_auto_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = build_save_config_payload(workspace, {"mode": "auto"})

    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    assert payload["config"]["mode"] == "auto"
    assert 'mode = "auto"' in config_text


def test_build_save_config_payload_rejects_unknown_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    try:
        build_save_config_payload(workspace, {"mode": "turbo"})
    except ValueError as exc:
        assert "mode must be" in str(exc)
    else:
        raise AssertionError("browser config must reject unknown modes")


def test_build_save_config_payload_rejects_non_string_mode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    try:
        build_save_config_payload(workspace, {"mode": ["auto"]})
    except ValueError as exc:
        assert "mode must be" in str(exc)
    else:
        raise AssertionError("browser config must reject non-string modes")


def test_build_save_config_payload_ignores_allowed_commands_update(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('allowed_commands = ["python"]\n', encoding="utf-8")

    payload = build_save_config_payload(workspace, {"allowed_commands": ["rm"]})

    config_text = config_path.read_text(encoding="utf-8")
    assert payload["config"]["allowed_commands"] == ["python"]
    assert 'allowed_commands = ["python"]' in config_text
    assert "rm" not in config_text


def test_build_save_config_payload_writes_project_config_without_secrets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = build_save_config_payload(
        workspace,
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "sandbox": "workspace-write",
            "approval": "risky-confirm",
            "dry_run": True,
            "web_search_enabled": True,
            "computer_read_enabled": True,
            "default_skills": ["code-dev"],
            "api_key": "must-not-be-written",
        },
    )

    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    assert payload["status"] == "ok"
    assert payload["config"]["provider"] == "deepseek"
    assert payload["config"]["dry_run"] is True
    assert payload["config"]["web_search_enabled"] is True
    assert payload["config"]["computer_read_enabled"] is True
    assert "web_search_enabled = true" in config_text
    assert "computer_read_enabled = true" in config_text
    assert 'default_skills = ["code-dev"]' in config_text
    assert "must-not-be-written" not in config_text
    assert "api_key" not in config_text


def test_build_save_config_payload_escapes_toml_strings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = 'deepseek-v4-"flash"\nnext = "bad"'

    build_save_config_payload(
        workspace,
        {
            "provider": "deepseek",
            "model": model,
            "sandbox": "workspace-write",
            "approval": "risky-confirm",
            "dry_run": False,
            "web_search_enabled": False,
            "computer_read_enabled": False,
            "default_skills": ["code-dev"],
        },
    )

    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    payload = build_config_payload(workspace)

    assert payload["config"]["model"] == model
    assert config_text.count("model = ") == 1


def test_build_save_config_payload_rejects_disabling_approvals(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    try:
        build_save_config_payload(workspace, {"approval": "never"})
    except ValueError as exc:
        assert "cannot disable approvals" in str(exc)
    else:
        raise AssertionError("browser config must not disable approvals")


def test_build_save_config_payload_keeps_previous_file_when_atomic_publish_fails(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    original = "dry_run = false\n"
    config_path.write_text(original, encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr("agent._user_store.os.replace", fail_replace)

    with pytest.raises(OSError, match="Could not save project config"):
        build_save_config_payload(workspace, {"dry_run": True})

    assert config_path.read_text(encoding="utf-8") == original
    assert list(config_path.parent.glob(".config.toml.agent-*.tmp")) == []


def test_build_health_payload_reports_deepseek_key_presence_without_leaking_value(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-value")

    payload = build_health_payload(workspace)

    assert payload["deepseek_api_key_env"] == "DEEPSEEK_API_KEY"
    assert payload["deepseek_api_key_present"] is True
    assert "sk-test-secret-value" not in repr(payload)


def test_build_health_payload_reads_workspace_secrets_without_leaking_value(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    secrets_path = workspace / ".agent" / "secrets.env"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text("DEEPSEEK_API_KEY=local-secret\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    payload = build_health_payload(workspace)

    assert payload["deepseek_api_key_present"] is True
    assert "local-secret" not in repr(payload)


def test_build_health_payload_reports_missing_deepseek_key(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    payload = build_health_payload(workspace)

    assert payload["deepseek_api_key_env"] == "DEEPSEEK_API_KEY"
    assert payload["deepseek_api_key_present"] is False


def test_build_health_payload_warns_when_workbench_uses_fake_provider(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = build_health_payload(workspace)

    assert payload["provider"] == "fake"
    assert payload["provider_notice"] == "已选择 FakeLLM。"


def test_build_health_payload_reports_deepseek_provider_status(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('provider = "deepseek"\nmodel = "deepseek-v4-flash"\n', encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    payload = build_health_payload(workspace)

    assert payload["provider"] == "deepseek"
    assert payload["provider_notice"] == "已选择 DeepSeek，但缺少 DEEPSEEK_API_KEY。"


def test_build_health_payload_treats_openai_compat_key_as_optional(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    payload = build_health_payload(workspace)

    assert payload["provider_notice"] == "已选择 OpenAI 兼容 Provider。"
    assert payload["api_key_env"] == "OPENAI_API_KEY"
    assert payload["api_key_present"] is False
    assert payload["api_key_required"] is False
    assert payload["settings_readiness"]["status"] == "ready"
    assert payload["settings_readiness"]["api_key_required"] is False


def test_build_health_payload_reports_required_openai_compat_base_url(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('provider = "openai-compat"\n', encoding="utf-8")

    payload = build_health_payload(workspace)

    assert payload["provider_notice"] == (
        "已选择 OpenAI 兼容 Provider，但缺少 base_url。请在 .agent/config.toml 设置 base_url。"
    )
    assert payload["settings_readiness"]["status"] == "needs-base-url"
    assert "Set base_url before live openai-compat runs." in payload["settings_readiness"]["checks"]


def test_build_health_payload_includes_read_only_settings_readiness(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('provider = "deepseek"\nmodel = "deepseek-v4-flash"\n', encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    payload = build_health_payload(workspace)

    assert payload["settings_readiness"]["mode"] == "read-only"
    assert payload["settings_readiness"]["status"] == "needs-api-key"
    assert payload["settings_readiness"]["provider"] == "deepseek"
    assert payload["settings_readiness"]["model"] == "deepseek-v4-flash"
    assert payload["settings_readiness"]["deepseek_api_key_present"] is False
    assert "Set DEEPSEEK_API_KEY before live DeepSeek runs." in payload["settings_readiness"]["checks"]


def test_build_health_payload_includes_workspace_risk_from_recent_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_failed"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_failed\n\n- status: error\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"run_command"}},"observation":{"status":"error","summary":"Command failed."}}\n',
        encoding="utf-8",
    )

    payload = build_health_payload(workspace)

    assert payload["workspace_risk"]["mode"] == "read-only"
    assert payload["workspace_risk"]["risk_level"] == "attention"
    assert payload["workspace_risk"]["signals"]["failed_runs"] == 1
    assert "Review failed recent runs." in payload["workspace_risk"]["checks"]


def test_build_health_payload_includes_read_only_memory_review(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = MemoryStore(workspace)
    pending = store.add_candidate(source_run_id="run_1", source_excerpt="Remember pytest workflow.")
    accepted = store.add_candidate(source_run_id="run_2", source_excerpt="Remember review workflow.")
    entry = store.accept_candidate(accepted.candidate_id)
    revised = store.revise_entry(entry.entry_id, "Remember current review workflow.")

    payload = build_health_payload(workspace)

    assert payload["memory_review"]["mode"] == "read-only"
    assert payload["memory_review"]["pending_count"] == 1
    assert payload["memory_review"]["active_count"] == 1
    assert payload["memory_review"]["candidates"][0]["candidate_id"] == pending.candidate_id
    assert payload["memory_review"]["entries"][0]["entry_id"] == revised.entry_id
    assert "Review pending memory candidates" in payload["memory_review"]["checks"]


def test_build_tools_payload_reuses_policy_categories() -> None:
    payload = build_tools_payload()
    tools = {tool["name"]: tool for tool in payload["tools"]}

    assert tools["read_file"]["category"] == "low-risk"
    assert tools["git_diff"]["category"] == "low-risk"
    assert tools["write_file"]["category"] == "confirmation-required"
    assert tools["write_file"]["dry_run"] == "skipped"
    assert tools["done"]["category"] == "terminal"


def test_build_runs_payload_lists_recent_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- status: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")

    payload = build_runs_payload(workspace, limit=5)

    assert payload["workspace"] == str(workspace.resolve())
    assert payload["runs"][0]["run_id"] == "run_test"
    assert payload["runs"][0]["summary_path"].endswith("summary.md")
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["risk_level"] == "low"


def test_build_runs_payload_marks_failed_runs_attention(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_failed"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_failed\n\n- status: error\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"write_file"}},"observation":{"status":"error","summary":"Approval required."}}\n',
        encoding="utf-8",
    )

    payload = build_runs_payload(workspace, limit=5)

    assert payload["runs"][0]["status"] == "error"
    assert payload["runs"][0]["risk_level"] == "attention"


def test_build_run_detail_payload_includes_summary_and_tool_calls(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- final: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"done"}},"observation":{"status":"ok","summary":"Done."},'
        '"trace":{"warning":"[agent warning] Provider returned multiple tool calls; calls outside the current single-call path were ignored."}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["run_id"] == "run_test"
    assert "final: ok" in payload["summary"]
    assert payload["tool_calls"][0]["valid"] is True
    assert payload["tool_calls"][0]["data"]["action"]["action"]["name"] == "done"
    assert payload["tool_calls"][0]["data"]["trace"]["warning"].startswith("[agent warning]")


def test_build_run_detail_payload_includes_read_only_replay(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- status: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        "\n".join(
            [
                '{"action":{"action":{"name":"list_dir"}},"observation":{"status":"ok","summary":"Listed workspace."},"trace":{"phase":"action","terminal":false,"policy_decision":"allow"}}',
                '{"action":{"action":{"name":"done"}},"observation":{"status":"ok","summary":"Finished."},"trace":{"phase":"action","terminal":true,"policy_decision":"allow"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["replay"] == {
        "mode": "read-only",
        "step_count": 2,
        "steps": [
            {
                "line_number": 1,
                "phase": "action",
                "action": "list_dir",
                "status": "ok",
                "summary": "Listed workspace.",
                "terminal": False,
                "policy_decision": "allow",
            },
            {
                "line_number": 2,
                "phase": "action",
                "action": "done",
                "status": "ok",
                "summary": "Finished.",
                "terminal": True,
                "policy_decision": "allow",
            },
        ],
    }


def test_build_run_detail_payload_includes_task_review(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text(
        "# Run run_test\n\n- completed: true\n- terminal_reason: done\n",
        encoding="utf-8",
    )
    (run_dir / "tool_calls.jsonl").write_text(
        "\n".join(
            [
                '{"action":{"action":{"name":"list_dir"}},"observation":{"status":"ok","summary":"Listed workspace."}}',
                '{"action":{"action":{"name":"done","args":{"changed_files":["notes.txt"]}}},"observation":{"status":"ok","summary":"Finished."}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["review"] == {
        "latest_action": "done",
        "last_observation_summary": "Finished.",
        "changed_files": ["notes.txt"],
        "snapshot_count": 0,
        "manual_checks": ["Open the changed files and review the saved summary."],
    }


def test_build_run_detail_payload_includes_workflow_hints(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- status: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"done","args":{"changed_files":["src/agent/web/server.py","tests/test_ui.py","README.md"]}}},"observation":{"status":"ok","summary":"Finished."}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["workflow"]["verification_commands"] == [
        "python -m pytest tests/test_ui.py -q",
        "python -m pytest tests/test_docs.py -q",
        "python -m pytest -q",
        "git diff --check",
    ]
    assert payload["workflow"]["review_steps"] == [
        "Open changed files from Task Review.",
        "Run the suggested verification commands before committing.",
    ]
    assert payload["workflow"]["mode"] == "read-only"
    assert payload["patch_review"]["risk_level"] == "medium"
    assert payload["patch_review"]["verification_commands"] == payload["workflow"]["verification_commands"]
    assert payload["patch_review"]["mode"] == "read-only"


def test_build_run_detail_payload_includes_failure_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- status: error\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"write_file"}},"observation":{"status":"error","summary":"Approval required.","error":{"code":"APPROVAL_REQUIRED","message":"Action requires approval."}}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["failure"] == {
        "status": "failed",
        "failure_count": 1,
        "latest_failure": {
            "line_number": 1,
            "action": "write_file",
            "status": "error",
            "summary": "Approval required.",
            "error_code": "APPROVAL_REQUIRED",
        },
        "next_checks": [
            "Read the failed observation summary.",
            "Inspect the trace around the failed action.",
            "Use Workflow Hints before changing code.",
        ],
    }
    assert payload["patch_review"]["risk_level"] == "attention"
    assert "Read Failure Summary before changing code." in payload["patch_review"]["checks"]


def test_build_run_detail_payload_includes_read_only_failure_recovery(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_failed"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_failed\n\n- status: error\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"run_command"}},"observation":{"status":"error","summary":"Command failed.","error":{"code":"TOOL_FAILED","message":"Command failed."}},"trace":{"phase":"action","terminal":true,"policy_decision":"allow"}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_failed")

    assert payload["recovery"]["mode"] == "read-only"
    assert payload["recovery"]["status"] == "needs-attention"
    assert payload["recovery"]["rollback_available"] is False
    assert payload["recovery"]["latest_failure"]["action"] == "run_command"
    assert "Inspect the failed action in Trace." in payload["recovery"]["steps"]
    assert "Do not retry tools from the browser." in payload["recovery"]["checks"]
    assert payload["recovery"]["next_action"] == "Inspect the failure, then patch or retry from a terminal workflow."


def test_build_run_detail_payload_includes_low_risk_patch_review(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- status: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"done"}},"observation":{"status":"ok","summary":"Finished."}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["patch_review"] == {
        "mode": "read-only",
        "risk_level": "low",
        "summary": "No failed observations or changed files recorded.",
        "checks": ["Review the summary and trace before taking action."],
        "verification_commands": ["Review the summary and trace before taking action."],
        "next_action": "No patch review action needed.",
    }


def test_build_files_payload_lists_workspace_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")

    payload = build_files_payload(workspace, "")
    items = {item["name"]: item for item in payload["entries"]}

    assert payload["path"] == "."
    assert items["README.md"]["kind"] == "file"
    assert items["src"]["kind"] == "dir"


def test_build_file_payload_reads_text_with_budget(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("abcdef", encoding="utf-8")

    payload = build_file_payload(workspace, "notes.txt", max_chars=4)

    assert payload["path"] == "notes.txt"
    assert payload["content"] == "abcd\n[truncated]"
    assert payload["truncated"] is True


def test_build_file_payload_rejects_outside_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("secret", encoding="utf-8")

    try:
        build_file_payload(workspace, "../outside.txt")
    except ValueError as exc:
        assert "SANDBOX_VIOLATION" in str(exc)
    else:
        raise AssertionError("outside file reads should be rejected")


def test_build_file_payload_reads_external_absolute_path_when_enabled(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("computer_read_enabled = true\n", encoding="utf-8")
    outside.write_text("external", encoding="utf-8")

    payload = build_file_payload(workspace, str(outside))

    assert payload["path"] == str(outside.resolve())
    assert payload["content"] == "external"


def test_build_file_payload_still_rejects_parent_escape_when_computer_read_enabled(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("computer_read_enabled = true\n", encoding="utf-8")
    outside.write_text("external", encoding="utf-8")

    try:
        build_file_payload(workspace, "../outside.txt")
    except ValueError as exc:
        assert "SANDBOX_VIOLATION" in str(exc)
    else:
        raise AssertionError("relative parent escapes should stay rejected")


def test_build_file_payload_reports_missing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    try:
        build_file_payload(workspace, "missing.txt")
    except ValueError as exc:
        assert "File not found" in str(exc)
    else:
        raise AssertionError("missing file reads should fail")


def test_build_file_payload_rejects_binary_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "data.bin").write_bytes(b"abc\x00def")

    try:
        build_file_payload(workspace, "data.bin")
    except ValueError as exc:
        assert "Binary file preview is not supported" in str(exc)
    else:
        raise AssertionError("binary previews should fail")


def test_build_search_payload_reuses_bounded_workspace_search(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text("first\nNeedle 中文\n", encoding="utf-8")
    (workspace / "notes.md").write_text("needle notes\n", encoding="utf-8")
    (workspace / "node_modules" / "pkg").mkdir(parents=True)
    (workspace / "node_modules" / "pkg" / "hidden.js").write_text("needle\n", encoding="utf-8")

    payload = build_search_payload(workspace, "needle")

    assert payload["query"] == "needle"
    assert payload["path"] == "."
    assert [(item["path"], item["line"]) for item in payload["matches"]] == [
        ("notes.md", 1),
        ("src/app.py", 2),
    ]
    assert payload["total_matches"] == 2
    assert payload["truncated"] is False
    assert payload["scan_truncated"] is False
    assert payload["scanned_files"] == 2

    glob_payload = build_search_payload(workspace, "*.py")
    assert glob_payload["matches"] == [
        {"path": "src/app.py", "kind": "path", "line": None, "excerpt": None}
    ]


def test_build_search_payload_bounds_query_scan_and_file_reads(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("needle\n", encoding="utf-8")
    (workspace / "b.txt").write_text("needle after limit\n", encoding="utf-8")
    (workspace / "large.txt").write_text("prefix needle\n", encoding="utf-8")
    monkeypatch.setattr(filesystem_tools, "MAX_SEARCH_FILES", 2)
    monkeypatch.setattr(filesystem_tools, "MAX_SEARCH_FILE_BYTES", 8)

    payload = build_search_payload(workspace, "needle")

    assert payload["scan_truncated"] is True
    assert payload["truncated"] is True
    assert payload["scanned_files"] == 2
    assert payload["matches"] == [
        {"path": "a.txt", "kind": "text", "line": 1, "excerpt": "needle"}
    ]
    assert payload["skipped_files"] == 1

    for query in ("", "   ", "x" * 201):
        with pytest.raises(ValueError):
            build_search_payload(workspace, query)


def test_build_search_payload_skips_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("needle secret\n", encoding="utf-8")
    try:
        (workspace / "linked.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    payload = build_search_payload(workspace, "needle")

    assert payload["matches"] == []
    assert payload["skipped_files"] == 1


def test_build_save_file_payload_writes_text_and_records_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("old\n", encoding="utf-8")

    payload = build_save_file_payload(workspace, {"path": "notes.txt", "content": "new\n"})

    assert payload["status"] == "ok"
    assert payload["path"] == "notes.txt"
    assert payload["bytes_written"] == 4
    assert target.read_text(encoding="utf-8") == "new\n"
    assert payload["snapshot_path"].startswith(".agent/runs/")
    assert payload["snapshot_path"].endswith("/snapshots/act_000001/original")

    detail = build_run_detail_payload(workspace, payload["run_id"])
    assert detail["snapshots"][0]["path"] == "notes.txt"
    assert detail["snapshots"][0]["snapshot_path"] == payload["snapshot_path"]
    assert detail["review"]["changed_files"] == ["notes.txt"]
    assert detail["review"]["snapshot_count"] == 1
    assert "Show diff" in detail["review"]["manual_checks"][1]
    assert detail["patch_review"]["risk_level"] == "medium"
    assert "Open changed files from Task Review." in detail["patch_review"]["checks"]
    assert "Use Show diff before Restore when checking snapshots." in detail["patch_review"]["checks"]
    assert "Workbench file editor" in detail["summary"]


def test_build_save_file_payload_rejects_outside_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "outside.txt").write_text("old\n", encoding="utf-8")

    try:
        build_save_file_payload(workspace, {"path": "../outside.txt", "content": "new\n"})
    except ValueError as exc:
        assert "SANDBOX_VIOLATION" in str(exc)
    else:
        raise AssertionError("outside file saves should be rejected")


def test_build_diff_payload_compares_snapshot_to_current_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    snapshot = workspace / ".agent" / "runs" / "run_test" / "snapshots" / "act" / "original"
    snapshot.parent.mkdir(parents=True)
    workspace.mkdir(exist_ok=True)
    (workspace / "notes.txt").write_text("new\n", encoding="utf-8")
    snapshot.write_text("old\n", encoding="utf-8")

    payload = build_diff_payload(workspace, "notes.txt", ".agent/runs/run_test/snapshots/act/original")

    assert payload["path"] == "notes.txt"
    assert payload["snapshot_path"] == ".agent/runs/run_test/snapshots/act/original"
    assert "--- snapshot/notes.txt" in payload["diff"]
    assert "+++ current/notes.txt" in payload["diff"]
    assert "-old" in payload["diff"]
    assert "+new" in payload["diff"]


def test_build_diff_payload_rejects_outside_snapshot_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("new\n", encoding="utf-8")
    outside.write_text("old\n", encoding="utf-8")

    try:
        build_diff_payload(workspace, "notes.txt", "../outside.txt")
    except ValueError as exc:
        assert "SANDBOX_VIOLATION" in str(exc)
    else:
        raise AssertionError("outside snapshot paths should be rejected")


def test_build_diff_payload_rejects_non_snapshot_run_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_summary = workspace / ".agent" / "runs" / "run_test" / "summary.md"
    run_summary.parent.mkdir(parents=True)
    (workspace / "notes.txt").write_text("new\n", encoding="utf-8")
    run_summary.write_text("internal\n", encoding="utf-8")

    try:
        build_diff_payload(workspace, "notes.txt", ".agent/runs/run_test/summary.md")
    except ValueError as exc:
        assert "Snapshot path must stay under .agent/runs snapshots" in str(exc)
    else:
        raise AssertionError("non-snapshot run files should be rejected")


def test_build_restore_snapshot_payload_restores_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "notes.txt"
    snapshot_dir = workspace / ".agent" / "runs" / "run_test" / "snapshots" / "act"
    original = snapshot_dir / "original"
    snapshot_dir.mkdir(parents=True)
    target.write_text("new\n", encoding="utf-8")
    original.write_text("old\n", encoding="utf-8")
    (snapshot_dir / "metadata.json").write_text(
        f'{{"path": "{target.as_posix()}", "previously_existed": true, "snapshot_file": "{original.as_posix()}"}}\n',
        encoding="utf-8",
    )

    payload = build_restore_snapshot_payload(
        workspace,
        {"path": "notes.txt", "snapshot_path": ".agent/runs/run_test/snapshots/act/original"},
    )

    assert payload["status"] == "ok"
    assert payload["action"] == "restored"
    assert payload["path"] == "notes.txt"
    assert target.read_text(encoding="utf-8") == "old\n"


def test_build_restore_snapshot_payload_deletes_file_created_by_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "notes.txt"
    snapshot_dir = workspace / ".agent" / "runs" / "run_test" / "snapshots" / "act"
    metadata = snapshot_dir / "metadata.json"
    snapshot_dir.mkdir(parents=True)
    target.write_text("new\n", encoding="utf-8")
    metadata.write_text(
        f'{{"path": "{target.as_posix()}", "previously_existed": false, "snapshot_file": null}}\n',
        encoding="utf-8",
    )

    payload = build_restore_snapshot_payload(
        workspace,
        {"path": "notes.txt", "snapshot_path": ".agent/runs/run_test/snapshots/act/metadata.json"},
    )

    assert payload["status"] == "ok"
    assert payload["action"] == "deleted"
    assert not target.exists()


def test_build_restore_snapshot_payload_rejects_metadata_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    snapshot_dir = workspace / ".agent" / "runs" / "run_test" / "snapshots" / "act"
    original = snapshot_dir / "original"
    snapshot_dir.mkdir(parents=True)
    original.write_text("old\n", encoding="utf-8")
    outside.write_text("new\n", encoding="utf-8")
    (snapshot_dir / "metadata.json").write_text(
        f'{{"path": "{outside.as_posix()}", "previously_existed": true, "snapshot_file": "{original.as_posix()}"}}\n',
        encoding="utf-8",
    )

    try:
        build_restore_snapshot_payload(
            workspace,
            {"path": "notes.txt", "snapshot_path": ".agent/runs/run_test/snapshots/act/original"},
        )
    except ValueError as exc:
        assert "SANDBOX_VIOLATION" in str(exc)
    else:
        raise AssertionError("metadata pointing outside the workspace should be rejected")


def test_build_chats_payload_lists_sessions_and_detail(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = _seed_chat(
        workspace,
        "chat_summary",
        ["summarize project goals", "then list commands"],
    )

    listing = build_chats_payload(workspace)
    detail = build_chat_payload(workspace, state.session_id)

    assert listing["chats"][0]["session_id"] == state.session_id
    assert listing["chats"][0]["turn_count"] == 2
    assert listing["chats"][0]["latest_user"] == "then list commands"
    assert listing["chats"][0]["title"] == "summarize project goals"
    assert detail["title"] == "summarize project goals"
    assert detail["session_id"] == state.session_id
    assert [turn["user"] for turn in detail["turns"]] == ["summarize project goals", "then list commands"]
    assert detail["turns"][0]["process"] == ["执行 done：Done."]
    assert "thinking_text" in detail["turns"][0]


def test_build_chat_payload_translates_run_command_capability_warning(tmp_path: Path) -> None:
    raw = (
        "Run commands execute local processes with the agent's OS permissions; "
        "workspace path checks do not fully contain file, network, or subprocess access. Approval is required."
    )
    state = _seed_chat(tmp_path, "chat_warning", ["run command"])
    state.turns[0].last_observation_summary = raw
    state.save(AgentConfig())

    turn = build_chat_payload(tmp_path, state.session_id)["turns"][0]

    assert turn["last_observation_summary"] == (
        "运行命令会以 Agent 当前的操作系统权限启动本地进程；"
        "工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。"
    )


def test_build_chats_payload_projects_conversation_state_list(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = ConversationState.create(workspace, session_id="chat_listed")
    calls: list[Path] = []

    def list_states(cls, cwd: Path) -> list[ConversationState]:
        calls.append(cwd)
        return [state]

    monkeypatch.setattr(ConversationState, "list", classmethod(list_states))

    payload = build_chats_payload(workspace)

    assert calls == [workspace.resolve()]
    assert [item["session_id"] for item in payload["chats"]] == ["chat_listed"]


def test_build_chat_rename_payload_updates_session_title(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = _seed_chat(workspace, "chat_rename", ["summarize project goals"])

    payload = build_chat_rename_payload(
        workspace,
        {"session_id": state.session_id, "title": "项目亮点"},
    )
    listing = build_chats_payload(workspace)
    detail = build_chat_payload(workspace, state.session_id)

    assert payload["status"] == "ok"
    assert payload["title"] == "项目亮点"
    assert listing["chats"][0]["title"] == "项目亮点"
    assert detail["title"] == "项目亮点"


def test_build_chat_delete_payload_removes_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = _seed_chat(workspace, "chat_delete", ["delete me"])

    payload = build_chat_delete_payload(workspace, {"session_id": state.session_id})

    assert payload == {"status": "ok", "session_id": state.session_id, "deleted": True}
    assert build_chats_payload(workspace)["chats"] == []
    assert not (workspace / ".agent" / "chats" / state.session_id).exists()


def test_build_chat_delete_payload_preserves_error_messages(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cases = [
        ({"session_id": "chat_missing"}, "Chat session not found: chat_missing"),
        ({"session_id": "../runs"}, "session_id resolves outside chats."),
    ]

    for request, expected in cases:
        try:
            build_chat_delete_payload(workspace, request)
        except ValueError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"expected deletion failure: {request}")
