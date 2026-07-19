from __future__ import annotations

import json

from agent.config import AgentConfig
from agent.core.actions import ErrorCode
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


def test_hooks_are_disabled_by_default(tmp_path) -> None:
    result = run_once("inspect project", FakeLLMClient(), cwd=tmp_path, run_id="run_hooks_default")

    assert result.observation.status == "ok"
    assert not (tmp_path / ".agent" / "runs" / "run_hooks_default" / "hooks.jsonl").exists()


def test_enabled_audit_hook_records_lifecycle_events(tmp_path) -> None:
    result = run_once(
        "inspect project",
        FakeLLMClient(),
        cwd=tmp_path,
        run_id="run_hooks_audit",
        config=AgentConfig(enabled_hooks=("audit",)),
    )

    lines = (tmp_path / ".agent" / "runs" / "run_hooks_audit" / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]

    assert result.observation.status == "ok"
    assert "before_run" in [record["event"] for record in records]
    assert "after_run" in [record["event"] for record in records]
    assert all(record["status"] == "ok" for record in records)
    assert records[0]["payload"]["run_id"] == "run_hooks_audit"


def test_before_tool_format_hook_records_post_tool_use_payload(tmp_path) -> None:
    result = run_once(
        "inspect project",
        FakeLLMClient(
            actions=[
                {
                    "message": "List.",
                    "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 5}},
                },
                {
                    "message": "Done.",
                    "action": {"name": "done", "args": {"final": "listed", "changed_files": [], "next_steps": []}},
                },
            ]
        ),
        cwd=tmp_path,
        run_id="run_before_tool_format",
        config=AgentConfig(enabled_hooks=("before_tool_format",)),
    )

    lines = (tmp_path / ".agent" / "runs" / "run_before_tool_format" / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]

    assert result.observation.status == "ok"
    assert any(record["event"] == "after_tool" and record["payload"]["action"] == "list_dir" for record in records)
    assert all(record["hook"] == "before_tool_format" for record in records)


def test_nonblocking_hook_failure_is_logged_without_blocking_run(tmp_path) -> None:
    result = run_once(
        "inspect project",
        FakeLLMClient(),
        cwd=tmp_path,
        run_id="run_hooks_nonblocking",
        config=AgentConfig(enabled_hooks=("fail",)),
    )

    text = (tmp_path / ".agent" / "runs" / "run_hooks_nonblocking" / "hooks.jsonl").read_text(encoding="utf-8")

    assert result.observation.status == "ok"
    assert "Hook failed." in text


def test_blocking_hook_failure_returns_error_observation(tmp_path) -> None:
    result = run_once(
        "inspect project",
        FakeLLMClient(
            actions=[
                {
                    "message": "List.",
                    "action": {"name": "list_dir", "args": {"path": ".", "max_entries": None}},
                }
            ]
        ),
        cwd=tmp_path,
        run_id="run_hooks_blocking",
        config=AgentConfig(enabled_hooks=("fail",), blocking_hooks=("fail",)),
    )

    assert result.observation.status == "error"
    assert result.observation.error is not None
    assert result.observation.error.code == ErrorCode.INTERNAL_ERROR
    assert "Blocking hook failed" in result.observation.error.message
