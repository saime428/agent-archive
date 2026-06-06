from __future__ import annotations

from datetime import datetime, timezone

from agent.config import AgentConfig
from agent.core.actions import parse_model_action
from agent.policy.approvals import classify_action

CREATED_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


def _action(name: str, args: dict):
    return parse_model_action(
        {
            "message": f"Run {name}.",
            "action": {"name": name, "args": args},
        },
        run_id="run_policy",
        action_index=1,
        created_at=CREATED_AT,
    )


def test_read_file_allows_by_default() -> None:
    action = _action("read_file", {"path": "notes.txt", "start_line": None, "max_lines": None})

    decision = classify_action(action, AgentConfig())

    assert decision.status == "allow"


def test_write_file_requires_approval_by_default() -> None:
    action = _action(
        "write_file",
        {"path": "notes.txt", "content": "hello\n", "create_parents": False},
    )

    decision = classify_action(action, AgentConfig())

    assert decision.status == "approval_required"
    assert decision.reason == "Action requires approval before execution."


def test_run_command_requires_approval_when_approval_never() -> None:
    action = _action("run_command", {"argv": ["python", "-c", "print('hi')"], "cwd": None, "timeout_seconds": 5})

    decision = classify_action(action, AgentConfig(approval="never"))

    assert decision.status == "approval_required"


def test_approval_always_requires_approval_for_list_dir() -> None:
    action = _action("list_dir", {"path": ".", "max_entries": None})

    decision = classify_action(action, AgentConfig(approval="always"))

    assert decision.status == "approval_required"


def test_approval_always_still_allows_done() -> None:
    action = _action("done", {"final": "ok", "changed_files": [], "next_steps": []})

    decision = classify_action(action, AgentConfig(approval="always"))

    assert decision.status == "allow"
