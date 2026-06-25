from __future__ import annotations

from pathlib import Path

from agent.llm.fake import FakeLLMClient
from agent.web.server import (
    build_chat_turn_payload,
    build_config_payload,
    build_file_payload,
    build_files_payload,
    build_run_detail_payload,
    build_runs_payload,
    build_tools_payload,
    static_file_path,
)


def test_build_config_payload_reports_effective_workspace_config(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".agent" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('provider = "fake"\nmode = "auto"\n', encoding="utf-8")

    payload = build_config_payload(workspace)

    assert payload["workspace"] == str(workspace.resolve())
    assert payload["config"]["provider"] == "fake"
    assert payload["config"]["mode"] == "auto"
    assert str(config_path.resolve()) in payload["diagnostics"]["loaded_files"]


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


def test_build_run_detail_payload_includes_summary_and_tool_calls(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# Run run_test\n\n- final: ok\n", encoding="utf-8")
    (run_dir / "tool_calls.jsonl").write_text(
        '{"action":{"action":{"name":"done"}},"observation":{"status":"ok","summary":"Done."}}\n',
        encoding="utf-8",
    )

    payload = build_run_detail_payload(workspace, "run_test")

    assert payload["run_id"] == "run_test"
    assert "final: ok" in payload["summary"]
    assert payload["tool_calls"][0]["valid"] is True
    assert payload["tool_calls"][0]["data"]["action"]["action"]["name"] == "done"


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
    monkeypatch.setattr("agent.web.server.make_llm", lambda config: llm)

    payload = build_chat_turn_payload(workspace, {"message": "write notes"})

    assert payload["status"] == "error"
    assert payload["approval_required"] is True
    assert payload["error_code"] == "APPROVAL_REQUIRED"
    assert payload["requested_action"] == "write_file"
    assert not (workspace / "notes.txt").exists()


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
    monkeypatch.setattr("agent.web.server.make_llm", lambda config: llm)

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

    monkeypatch.setattr("agent.web.server.make_llm", make_write_llm)

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
    script = static_file_path("assets/app.js").read_text(encoding="utf-8")
    styles = static_file_path("assets/app.css").read_text(encoding="utf-8")

    assert "Agent Workbench" in index
    assert "message-input" in index
    assert "/api/health" in script
    assert "/api/runs" in script
    assert "/api/files" in script
    assert "/api/file" in script
    assert "/api/chat/turn" in script
    assert "window.confirm" in script
    assert "Snapshots" in index
    assert ".workbench-shell" in styles
