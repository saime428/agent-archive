from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent.core.chat import ConversationState
from agent.core.memory import MemoryStore
from agent.llm.fake import FakeLLMClient
from agent.web.chats import (
    build_chat_delete_payload,
    build_chat_payload,
    build_chat_rename_payload,
    build_chat_turn_payload,
    build_chats_payload,
)
from agent.web.files import (
    build_diff_payload,
    build_file_payload,
    build_files_payload,
    build_restore_snapshot_payload,
    build_save_file_payload,
)
from agent.web.runs import build_run_detail_payload, build_runs_payload
from agent.web.server import static_file_path
from agent.web.settings import (
    build_health_payload,
    build_config_payload,
    build_save_config_payload,
    build_tools_payload,
)


class RepairThenDoneLLM:
    def __init__(self) -> None:
        self.index = 0

    def chat(self, messages: list[dict], *, temperature: float | None = None):
        self.index += 1
        if self.index == 1:
            return "{not-json"
        return {
            "message": "Ready.",
            "action": {
                "name": "done",
                "args": {
                    "final": "已就绪，等待用户描述任务。",
                    "changed_files": [],
                    "next_steps": [],
                },
            },
        }


JS_MODULES = [
    "assets/app.js",
    "assets/state.js",
    "assets/api.js",
    "assets/sse.js",
    "assets/render/health.js",
    "assets/render/chat.js",
    "assets/render/runs.js",
    "assets/render/files.js",
    "assets/render/editor.js",
    "assets/render/resources.js",
    "assets/render/diagnostics.js",
    "assets/render/ui.js",
]


def _read_static_scripts() -> str:
    return "\n".join(static_file_path(path).read_text(encoding="utf-8") for path in JS_MODULES)


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


def test_settings_form_writes_run_mode() -> None:
    index = static_file_path("index.html").read_text(encoding="utf-8")
    state_script = static_file_path("assets/state.js").read_text(encoding="utf-8")
    health_script = static_file_path("assets/render/health.js").read_text(encoding="utf-8")

    assert 'id="settings-mode"' in index
    assert '<option value="auto">' in index
    assert 'settingsMode: document.querySelector("#settings-mode")' in state_script
    assert 'els.settingsMode.value = config.mode || "guided"' in health_script
    assert "mode: els.settingsMode.value" in health_script


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

    payload = build_health_payload(workspace)

    assert payload["memory_review"]["mode"] == "read-only"
    assert payload["memory_review"]["pending_count"] == 1
    assert payload["memory_review"]["active_count"] == 1
    assert payload["memory_review"]["candidates"][0]["candidate_id"] == pending.candidate_id
    assert payload["memory_review"]["entries"][0]["entry_id"] == entry.entry_id
    assert "Review pending memory candidates" in payload["memory_review"]["checks"]


def test_build_tools_payload_reuses_policy_categories() -> None:
    payload = build_tools_payload()
    tools = {tool["name"]: tool for tool in payload["tools"]}

    assert tools["read_file"]["category"] == "low-risk"
    assert tools["git_diff"]["category"] == "low-risk"
    assert tools["write_file"]["category"] == "confirmation-required"
    assert tools["write_file"]["dry_run"] == "skipped"
    assert tools["done"]["category"] == "terminal"


def test_app_js_avoids_dynamic_inner_html_xss_paths() -> None:
    script = _read_static_scripts()

    assert "${emptyText}" not in script
    assert "els.fileList.innerHTML = `<div class=\"empty-state\">${error" not in script
    assert "function emptyStateElement" in script


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


def test_build_chat_turn_payload_runs_fake_chat_and_persists_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = build_chat_turn_payload(workspace, {"message": "inspect project"})

    assert payload["session_id"].startswith("chat_")
    assert payload["turn_count"] == 1
    assert payload["status"] == "ok"
    assert payload["completed"] is True
    assert payload["terminal_reason"] == "done"
    assert payload["final"] == "FakeLLM received task: inspect project"
    assert (workspace / ".agent" / "chats" / payload["session_id"] / "session.json").is_file()
    assert (workspace / ".agent" / "runs" / payload["run_id"] / "summary.md").is_file()
    assert payload["repair_count"] == 0
    assert payload["has_repair_noise"] is False
    assert payload["display_status"] == "completed"
    assert payload["process"] == ["整理最终回答。"]
    assert "thinking_text" in payload
    assert "整理最终回答" in payload["thinking_text"]
    assert "Task completed by FakeLLM." in payload["thinking_text"]


def test_build_chat_turn_payload_resumes_existing_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = build_chat_turn_payload(workspace, {"message": "first"})

    second = build_chat_turn_payload(
        workspace,
        {"session_id": first["session_id"], "message": "second"},
    )

    assert second["session_id"] == first["session_id"]
    assert second["turn_count"] == 2
    assert second["final"] == "FakeLLM received task: second"


def test_build_chat_turn_payload_creates_requested_new_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = build_chat_turn_payload(workspace, {"session_id": "chat_manual", "message": "hello"})

    assert payload["session_id"] == "chat_manual"
    assert payload["turn_count"] == 1
    assert (workspace / ".agent" / "chats" / "chat_manual" / "session.json").is_file()


def test_build_chat_turn_payload_marks_repaired_turn_as_completed(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: RepairThenDoneLLM())

    payload = build_chat_turn_payload(workspace, {"message": "inspect project"})

    assert payload["status"] == "ok"
    assert payload["completed"] is True
    assert payload["display_status"] == "completed"
    assert payload["repair_count"] == 1
    assert payload["has_repair_noise"] is True
    assert payload["final"] == "已就绪，等待用户描述任务。"
    assert "模型输出格式不符合动作协议" not in payload["thinking_text"]
    assert "invalid_model_response" not in payload["thinking_text"]
    assert "Model response" not in payload["thinking_text"]


def test_build_chat_turn_payload_displays_ask_user_question(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Ask.",
                "action": {
                    "name": "ask_user",
                    "args": {"question": "Please describe the task you want me to complete."},
                },
            }
        ]
    )
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "inspect project"})

    assert payload["status"] == "ok"
    assert payload["completed"] is False
    assert payload["terminal_reason"] == "ask_user"
    assert payload["display_status"] == "ask_user"
    assert payload["final"] == "Please describe the task you want me to complete."


def test_build_chat_turn_payload_answers_simple_greeting(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient()
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "你好"})

    assert payload["completed"] is True
    assert payload["terminal_reason"] == "done"
    assert "你好，我在" in payload["final"]
    assert payload["process"] == ["整理最终回答。"]
    assert "thinking_text" in payload
    assert "整理最终回答" in payload["thinking_text"]


def test_build_chats_payload_lists_sessions_and_detail(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = build_chat_turn_payload(workspace, {"message": "summarize project goals"})
    build_chat_turn_payload(workspace, {"session_id": first["session_id"], "message": "then list commands"})

    listing = build_chats_payload(workspace)
    detail = build_chat_payload(workspace, first["session_id"])

    assert listing["chats"][0]["session_id"] == first["session_id"]
    assert listing["chats"][0]["turn_count"] == 2
    assert listing["chats"][0]["latest_user"] == "then list commands"
    assert listing["chats"][0]["title"] == "summarize project goals"
    assert detail["title"] == "summarize project goals"
    assert detail["session_id"] == first["session_id"]
    assert [turn["user"] for turn in detail["turns"]] == ["summarize project goals", "then list commands"]
    assert detail["turns"][0]["process"] == ["整理最终回答。"]
    assert "thinking_text" in detail["turns"][0]


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
    first = build_chat_turn_payload(workspace, {"message": "summarize project goals"})

    payload = build_chat_rename_payload(
        workspace,
        {"session_id": first["session_id"], "title": "项目亮点"},
    )
    listing = build_chats_payload(workspace)
    detail = build_chat_payload(workspace, first["session_id"])

    assert payload["status"] == "ok"
    assert payload["title"] == "项目亮点"
    assert listing["chats"][0]["title"] == "项目亮点"
    assert detail["title"] == "项目亮点"


def test_build_chat_delete_payload_removes_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = build_chat_turn_payload(workspace, {"message": "delete me"})

    payload = build_chat_delete_payload(workspace, {"session_id": first["session_id"]})

    assert payload == {"status": "ok", "session_id": first["session_id"], "deleted": True}
    assert build_chats_payload(workspace)["chats"] == []
    assert not (workspace / ".agent" / "chats" / first["session_id"]).exists()


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


def test_build_chat_turn_payload_includes_public_action_message_in_process(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Check the workspace files first.",
                "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 10}},
            },
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "Checked files.", "changed_files": [], "next_steps": []},
                },
            },
        ]
    )
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "inspect files"})

    assert "Check the workspace files first." in payload["thinking_text"]
    assert "invalid_model_response" not in payload["thinking_text"]


def test_build_chat_turn_payload_rejects_empty_message(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    try:
        build_chat_turn_payload(workspace, {"message": "  "})
    except ValueError as exc:
        assert "message is required" in str(exc)
    else:
        raise AssertionError("empty chat messages should be rejected")


def test_build_chat_turn_payload_reports_approval_required(monkeypatch, tmp_path: Path) -> None:
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
            }
        ]
    )
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "write notes"})

    assert payload["status"] == "error"
    assert payload["approval_required"] is True
    assert payload["error_code"] == "APPROVAL_REQUIRED"
    assert payload["requested_action"] == "write_file"
    assert payload["last_observation_summary"] == "这个操作需要你先在右侧审查里批准。"
    assert "需要你批准后才会执行" in payload["thinking_text"]
    assert "没有完成" not in payload["thinking_text"]
    assert not (workspace / "notes.txt").exists()


def test_build_chat_turn_payload_translates_run_command_capability_warning(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "should-not-exist.txt"
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Run command.",
                "action": {
                    "name": "run_command",
                    "args": {
                        "argv": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('should-not-exist.txt').write_text('x')",
                        ],
                        "cwd": None,
                        "timeout_seconds": 5,
                    },
                },
            }
        ]
    )
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "run command"})

    expected = "运行命令会以 Agent 当前的操作系统权限启动本地进程；工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。"
    assert payload["last_observation_summary"] == expected
    assert build_chat_payload(workspace, payload["session_id"])["turns"][-1]["last_observation_summary"] == expected
    assert not marker.exists()


def test_build_chat_turn_payload_approve_once_executes_one_required_action(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr("agent.web.chats.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "write notes", "approve_once": True})

    assert payload["status"] == "ok"
    assert payload["approval_required"] is False
    assert payload["terminal_reason"] == "done"
    assert payload["final"] == "Wrote notes."
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello\n"


def test_build_chat_turn_payload_approval_retry_uses_same_session(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def make_write_llm(_config):
        return FakeLLMClient(
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

    monkeypatch.setattr("agent.web.chats.make_llm", make_write_llm)

    first = build_chat_turn_payload(workspace, {"message": "write notes"})
    second = build_chat_turn_payload(
        workspace,
        {"session_id": first["session_id"], "message": "write notes", "approve_once": True},
    )

    assert first["approval_required"] is True
    assert second["session_id"] == first["session_id"]
    assert second["status"] == "ok"
    assert second["turn_count"] == 2
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello\n"


def test_static_workbench_assets_exist_and_reference_api() -> None:
    index = static_file_path("index.html").read_text(encoding="utf-8")
    script = _read_static_scripts()
    entry_script = static_file_path("assets/app.js").read_text(encoding="utf-8")
    sse_script = static_file_path("assets/sse.js").read_text(encoding="utf-8")
    chat_script = static_file_path("assets/render/chat.js").read_text(encoding="utf-8")
    diagnostics_script = static_file_path("assets/render/diagnostics.js").read_text(encoding="utf-8")
    styles = static_file_path("assets/app.css").read_text(encoding="utf-8")

    assert "Agent Workbench" in index
    for path in JS_MODULES:
        assert static_file_path(path).is_file()
    assert 'type="module"' in index
    assert '"./state.js"' in entry_script
    assert '"./api.js"' in entry_script
    assert '"./sse.js"' in entry_script
    assert 'from "./render/' in entry_script
    assert "void " not in entry_script
    assert "EventSource" in sse_script
    assert '"approval_timed_out",' in sse_script
    assert (
        "Run commands execute local processes with the agent's OS permissions; workspace path checks do not fully "
        "contain file, network, or subprocess access. Approval is required."
    ) in chat_script
    assert "运行命令会以 Agent 当前的操作系统权限启动本地进程；工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。" in chat_script
    assert "const reason = friendlyChatText(event.reason);" in chat_script
    assert "return null" not in sse_script
    assert "function openChatEventSource" not in chat_script
    assert "export const " not in "\n".join(
        static_file_path(path).read_text(encoding="utf-8")
        for path in JS_MODULES
        if path.startswith("assets/render/") and path != "assets/render/chat.js"
    )
    assert "TOKEN/CODEX" not in index
    assert "new-task-button" in index
    assert "聊天" in index
    assert "文件" in index
    assert "数据中心" in index
    assert "设置" in index
    assert 'data-view="chat"' in index
    assert 'data-view="editor"' in index
    assert 'data-view="resources"' in index
    assert 'data-view="settings"' in index
    assert "message-input" in index
    assert 'aria-label="消息"' in index
    assert "recent-file-list" in index
    assert "resource-summary-list" in index
    assert "settings-tool-list" in index
    assert "settings-key-status" in index
    assert "settings-web-search" in index
    assert "settings-computer-read" in index
    assert 'if (config.approval === "never")' in script
    assert 'option.textContent = "never (global)";' in script
    assert "option.disabled = true;" in script
    assert "globalNeverOption?.remove();" in script
    assert 'if (els.settingsApproval.value !== "never")' in script
    assert "payload.approval = els.settingsApproval.value;" in script
    assert 'data-settings-target="settings-api-section"' in index
    assert 'data-settings-target="settings-runtime-section"' in index
    assert 'data-settings-target="settings-tools-section"' in index
    assert 'id="settings-api-section"' in index
    assert 'id="settings-runtime-section"' in index
    assert 'id="settings-tools-section"' in index
    assert "运行权限" in index
    assert "审批策略" not in index
    assert "Codex CLI" not in index
    assert 'aria-label="文件编辑器"' in index
    assert "追加消息..." in index
    assert "chat-thread" in index
    assert "conversation-tabs" in index
    assert "left-resizer" in index
    assert "right-resizer" in index
    assert "resource-detail-modal" in index
    assert "context-column" in index
    assert "stage-column" in index
    assert "assistant-column" in index
    assert "tokenicode-shell" in index
    assert "window-dot" not in index
    assert "diagnostics-drawer" not in index
    assert "diagnostics-toggle" not in index
    assert "rail-diagnostics-toggle" not in index
    assert "side-tabs" in index
    assert 'data-side-panel="review"' in index
    assert 'data-side-panel="terminal"' in index
    assert 'data-side-panel="files"' in index
    assert 'data-side-panel="chat"' in index
    assert 'aria-label="回到聊天"' in index
    assert "terminal-output" in index
    assert "side-file-list" in index
    assert "side-chat-list" in index
    assert "web-search-toggle" in index
    assert "computer-read-toggle" in index
    assert "native-tools-toggle" in index
    assert "thinking-toggle" in index
    assert "api-key-chip" not in index
    assert "mode-chip" not in index
    assert "sandbox-chip" not in index
    assert "/api/health" in script
    assert "/api/config" in script
    assert "/api/chats" in script
    assert "/api/runs" in script
    assert "/api/files" in script
    assert "/api/file" in script
    assert "/api/file/save" in script
    assert "/api/diff" in script
    assert "/api/snapshot/restore" in script
    assert "/api/chat/turn" in script
    assert "/api/chat/start" in script
    assert "/api/chat/events" in script
    assert "/api/chat/approval" in script
    assert "/api/chat/rename" in script
    assert "/api/chat/delete" in script
    assert "thinking_text" in script
    assert "renderConversationTabs" in script
    assert "chat.title" in script
    assert "chat-row" in script
    assert "renderThinkingText" in script
    assert "renderThinkingTextTyping" in script
    typing_renderer = chat_script[
        chat_script.index("function renderThinkingTextTyping") : chat_script.index("function renderProcessCards")
    ]
    assert "if (!container.contains(target))" in typing_renderer
    assert "keydown" in script
    assert "isComposing" in script
    assert "shiftKey" in script
    assert "settingsNavButtons" in script
    assert "scrollToSetting" in script
    assert "scrollIntoView" in script
    assert "computer_read_enabled" in script
    assert "modeChip" not in script
    assert "sandboxChip" not in script
    assert "model_stream_chunk" in script
    assert "toggleConfigKey" in script
    assert "renderChipToggles" in script
    assert "config.allowed_commands" in script
    assert "命令白名单" in script
    assert "allowed_commands:" not in script
    assert "stream-live-text" in styles
    assert "chip-toggle" in styles
    assert "Recovered after" not in script
    assert "invalid_model_response" not in script
    assert "window.confirm" not in script
    assert "approval-panel" in index
    assert "approve-button" in index
    assert "deny-button" in index
    assert "file-editor" in index
    assert "save-file-button" in index
    assert "showApprovalPanel" in script
    assert "保存文件" in script
    assert "恢复" in script
    assert "refreshWorkbench" in script
    assert "renderDiagnostics" in script
    assert 'id="tool-call-list"' in index
    assert "const warning = call.data?.trace?.warning;" in diagnostics_script
    assert "warning ? `${warning}\\n${summary}` : summary" in diagnostics_script
    assert "Provider API key" in script
    assert 'status.api_key_required ? "缺失" : "未配置（可选）"' in script
    assert "web_search_enabled" in script
    assert "display_status" in script
    assert "repair_count" in script
    assert "thought-process" in script
    assert "closeConversationTab" in script
    assert "tab-close" in script
    assert "chat-menu-button" in script
    assert "renameChat" in script
    assert "deleteChat" in script
    assert "showActionError" in script
    assert "backendErrorMessage" in script
    assert "globalThis.confirm" in script
    assert "initColumnResize" in script
    assert "renderPagedList" in script
    assert "openResourceDetail" in script
    assert "resourcePanels" in script
    assert "resourcePreviewItem" in script
    assert "data-resource-expand" not in index
    assert "buildPendingProcess" not in script
    assert "pendingRouteFor" not in script
    assert "代码/项目修改" not in script
    assert "网页/视觉设计" not in script
    assert "EventSource" in script
    assert "renderLiveTurnIncrement" in script
    handle_chat_event = sse_script[sse_script.index("function handleChatEvent") :]
    assert "renderChatThread" not in handle_chat_event
    assert "renderProcessCards" in script
    assert "process-step-card" in script
    assert "submitApproval" in script
    assert '["approval_granted", "approval_denied", "approval_timed_out"]' in chat_script
    assert 'event.event === "approval_timed_out"' in chat_script
    assert 'approval_timed_out: "审批超时"' in chat_script
    assert 'return "审批超时。";' in chat_script
    assert "renderMessageBody" in script
    assert "renderCodeBlock" in script
    assert "renderMarkdownTable" in script
    assert 'document.createElement("a")' in script
    assert 'document.createElement("strong")' in script
    assert 'article.querySelector(".message-body").textContent = body;' not in script
    assert "已收到你的输入" not in script
    assert "details.open = Boolean(options.openThinking);" in script
    assert 'state.animateLatestRunId = "__pending__";' in script
    assert "state.animateLatestRunId = turn.run_id;" not in script
    start_new_chat = script[script.index("function startNewChat()") : script.index("function renderChatThread")]
    assert 'activateView("chat");' in start_new_chat
    assert "SEARCH_DEBOUNCE_MS = 200" in script
    assert "debounce(" in script
    assert "等待审批" in script
    assert "快照" in index
    assert "任务审查" in index
    assert "补丁审查" in index
    assert "details-pane" not in index
    assert "height: 100vh" in styles
    assert "overflow: hidden" in styles
    assert "@layer base, layout, components, utilities;" in styles
    assert ".apix-shell" in styles
    assert "--surface:" in styles
    assert "--accent:" in styles
    assert "--text:" in styles
    assert "color-scheme" in styles
    assert ".token-sidebar" in styles
    assert ".new-task-button" in styles
    assert ".conversation-tabs" in styles
    assert ".conversation-tab" in styles
    assert ".tab-close" in styles
    assert ".column-resizer" in styles
    assert ".chat-menu" in styles
    assert ".pagination-row" in styles
    assert ".resource-preview-item" in styles
    assert ".resource-detail-modal" in styles
    assert ".chat-row" in styles
    assert ".app-view.active" in styles
    assert ".side-tabs" in styles
    assert ".side-panel.active" in styles
    assert "#side-review #run-list" in styles
    assert "#selected-run-title" in styles
    assert ".settings-nav button" in styles
    assert ".terminal-output" in styles
    assert ".thought-process" in styles
    assert ".process-step-card" in styles
    assert ".copy-code-button" in styles
    assert ".markdown-table" in styles
    assert '[data-theme="dark"]' in styles
    assert ".token-secondary" in styles
    assert "@keyframes view-rise" in styles
    assert "@media (prefers-reduced-motion: no-preference)" in styles
