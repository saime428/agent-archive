from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from agent.config import AgentConfig
from agent.core.actions import parse_model_action
from agent.core.tool_catalog import build_tool_catalog
from agent.mcp_runtime import McpToolDefinition, McpToolTarget
from agent.policy.approvals import classify_action

CREATED_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
RUN_COMMAND_APPROVAL_REASON = (
    "Run commands execute local processes with the agent's OS permissions; "
    "workspace path checks do not fully contain file, network, or subprocess access. Approval is required."
)


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


def test_run_command_requires_capability_approval_by_default() -> None:
    action = _action("run_command", {"argv": ["python", "-c", "print('hi')"], "cwd": None, "timeout_seconds": 5})

    decision = classify_action(action, AgentConfig())

    assert decision.status == "approval_required"
    assert decision.reason == RUN_COMMAND_APPROVAL_REASON


def test_run_command_is_denied_when_approval_never() -> None:
    action = _action("run_command", {"argv": ["python", "-c", "print('hi')"], "cwd": None, "timeout_seconds": 5})

    decision = classify_action(action, AgentConfig(approval="never"))

    assert decision.status == "deny"
    assert decision.reason == "Approval is disabled; confirmation-required actions are denied."


def test_read_only_reason_takes_precedence_over_approval_never() -> None:
    action = _action(
        "write_file",
        {"path": "notes.txt", "content": "hello\n", "create_parents": False},
    )

    decision = classify_action(action, AgentConfig(approval="never", sandbox="read-only"))

    assert decision.status == "deny"
    assert decision.reason == "Action is blocked by read-only sandbox."


def test_approval_always_requires_approval_for_list_dir() -> None:
    action = _action("list_dir", {"path": ".", "max_entries": None})

    decision = classify_action(action, AgentConfig(approval="always"))

    assert decision.status == "approval_required"
    assert decision.reason == "Action requires approval before execution."


def test_approval_always_uses_run_command_capability_reason() -> None:
    action = _action("run_command", {"argv": ["python", "-c", "print('hi')"], "cwd": None, "timeout_seconds": 5})

    decision = classify_action(action, AgentConfig(approval="always"))

    assert decision.status == "approval_required"
    assert decision.reason == RUN_COMMAND_APPROVAL_REASON


def test_approval_always_still_allows_done() -> None:
    action = _action("done", {"final": "ok", "changed_files": [], "next_steps": []})

    decision = classify_action(action, AgentConfig(approval="always"))

    assert decision.status == "allow"

def _mcp_action_and_definition():
    schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    runtime_definition = McpToolDefinition(
        exposed_name="mcp__local__echo",
        target=McpToolTarget(
            server_id="local",
            remote_name="echo",
            snapshot_contract=SimpleNamespace(output_validator=None),
        ),
        description="Echo.",
        input_schema=schema,
        output_schema=None,
        input_validator=Draft202012Validator(dict(schema)),
    )
    catalog = build_tool_catalog((runtime_definition,))
    action = parse_model_action(
        {
            "message": "Call echo.",
            "action": {
                "name": "mcp__local__echo",
                "args": {"message": "hello"},
            },
        },
        run_id="run_policy",
        action_index=1,
        created_at=CREATED_AT,
        tool_catalog=catalog,
    )
    return action, catalog.resolve("mcp__local__echo")


def test_mcp_tool_always_requires_identity_rich_approval() -> None:
    action, definition = _mcp_action_and_definition()

    decision = classify_action(action, AgentConfig(), definition)

    assert decision.status == "approval_required"
    assert "mcp__local__echo" in decision.reason
    assert "local" in decision.reason
    assert "echo" in decision.reason
    assert "OS permissions" in decision.reason


def test_mcp_tool_is_denied_when_approval_is_disabled() -> None:
    action, definition = _mcp_action_and_definition()

    decision = classify_action(action, AgentConfig(approval="never"), definition)

    assert decision.status == "deny"
    assert "mcp__local__echo" in decision.reason
    assert "Approval is disabled" in decision.reason


def test_mcp_tool_is_denied_in_read_only_sandbox() -> None:
    action, definition = _mcp_action_and_definition()

    decision = classify_action(
        action,
        AgentConfig(approval="always", sandbox="read-only"),
        definition,
    )

    assert decision.status == "deny"
    assert "mcp__local__echo" in decision.reason
    assert "read-only" in decision.reason
