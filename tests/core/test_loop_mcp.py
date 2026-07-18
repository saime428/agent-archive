from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from agent.config import AgentConfig
from agent.core.actions import ErrorCode
from agent.core.loop import run_once
from agent.core.tool_catalog import ToolCatalogError
from agent.mcp_runtime import (
    McpCallResult,
    McpToolDefinition,
    McpToolTarget,
)


def _schema(*, padding: int = 0) -> dict:
    schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    if padding:
        schema["description"] = "x" * padding
    return schema


def _definition(
    name: str = "mcp__local__echo",
    *,
    server_id: str = "local",
    remote_name: str = "echo",
    padding: int = 0,
) -> McpToolDefinition:
    public_schema = _schema(padding=padding)
    validator_schema = deepcopy(public_schema)
    return McpToolDefinition(
        exposed_name=name,
        target=McpToolTarget(
            server_id=server_id,
            remote_name=remote_name,
            snapshot_contract=SimpleNamespace(output_validator=None),
        ),
        description=f"Call {remote_name}.",
        input_schema=public_schema,
        output_schema=None,
        input_validator=Draft202012Validator(validator_schema),
    )


class FakeRuntime:
    def __init__(
        self,
        definitions: tuple[McpToolDefinition, ...] | None = None,
        results: list[McpCallResult] | None = None,
    ) -> None:
        self.definitions = definitions or (_definition(),)
        self.results = list(results or [McpCallResult(status="ok", summary="echoed", data={"text": "hello"})])
        self.discover_calls = 0
        self.calls: list[tuple[McpToolTarget, dict]] = []
        self.command = "must-not-enter-trace"
        self.pass_env = {"TOKEN": "must-not-enter-trace"}

    def discover_tools(self) -> tuple[McpToolDefinition, ...]:
        self.discover_calls += 1
        return self.definitions

    def call_tool(self, target: McpToolTarget, arguments: dict) -> McpCallResult:
        self.calls.append((target, dict(arguments)))
        if not self.results:
            raise AssertionError("FakeRuntime ran out of results.")
        return self.results.pop(0)


class ScriptedLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        self.calls.append([dict(message) for message in messages])
        if not self.responses:
            raise AssertionError("ScriptedLLM ran out of responses.")
        return self.responses.pop(0)


class ScriptedNativeLLM(ScriptedLLM):
    def __init__(self, responses: list[dict]) -> None:
        super().__init__(responses)
        self.tool_payloads: list[list[dict]] = []

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        raise AssertionError("JSON fallback must not run in native mode.")

    def chat_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict:
        self.calls.append([dict(message) for message in messages])
        self.tool_payloads.append(tools)
        if not self.responses:
            raise AssertionError("ScriptedNativeLLM ran out of responses.")
        return self.responses.pop(0)


def _mcp_action(message: str = "hello", *, args: dict | None = None) -> dict:
    return {
        "message": "Call MCP echo.",
        "action": {
            "name": "mcp__local__echo",
            "args": args if args is not None else {"message": message},
        },
    }


def _done(final: str = "done") -> dict:
    return {
        "message": "Done.",
        "action": {
            "name": "done",
            "args": {"final": final, "changed_files": [], "next_steps": []},
        },
    }


def test_json_fallback_registers_calls_and_traces_one_frozen_mcp_tool(tmp_path) -> None:
    runtime = FakeRuntime()
    llm = ScriptedLLM([_mcp_action(), _done()])
    events: list[dict] = []

    result = run_once(
        "call echo",
        llm,
        cwd=tmp_path,
        run_id="run_mcp_json",
        mcp_runtime=runtime,
        approval_handler=lambda _action: True,
        event_handler=events.append,
    )

    assert runtime.discover_calls == 1
    assert len(runtime.calls) == 1
    assert runtime.calls[0][1] == {"message": "hello"}
    assert result.observations[0].status == "ok"
    assert result.observations[0].data == {
        "source": "mcp",
        "server_id": "local",
        "remote_tool": "echo",
        "result": {"text": "hello"},
    }

    system = llm.calls[0][0]["content"]
    assert "mcp__local__echo" in system
    assert '"parameters"' in system
    assert "untrusted server metadata" in system

    ordered = [
        event["event"]
        for event in events
        if event["event"]
        in {
            "action_parsed",
            "tool_start",
            "approval_required",
            "approval_granted",
            "observation",
        }
    ]
    assert ordered[:5] == [
        "action_parsed",
        "tool_start",
        "approval_required",
        "approval_granted",
        "observation",
    ]
    approval_event = next(event for event in events if event["event"] == "approval_required")
    assert "mcp__local__echo" in approval_event["reason"]
    assert "OS permissions" in approval_event["reason"]

    first_record = json.loads(result.tool_calls_path.read_text(encoding="utf-8").splitlines()[0])
    trace = first_record["trace"]
    assert trace["tool_source"] == "mcp"
    assert trace["server_id"] == "local"
    assert trace["remote_name"] == "echo"
    assert "mcp__local__echo" in trace["policy_reason"]
    assert trace["config"]["mcp_servers"] == [{"server_id": "local"}]
    serialized = json.dumps(first_record, ensure_ascii=False)
    assert "must-not-enter-trace" not in serialized
    assert "pass_env" not in serialized


def test_native_mode_uses_the_same_dynamic_catalog(tmp_path) -> None:
    runtime = FakeRuntime()
    llm = ScriptedNativeLLM([_mcp_action(), _done()])

    result = run_once(
        "call echo",
        llm,
        cwd=tmp_path,
        run_id="run_mcp_native",
        config=AgentConfig(native_tools=True),
        mcp_runtime=runtime,
        approval_handler=lambda _action: True,
    )

    assert result.observations[0].status == "ok"
    assert runtime.discover_calls == 1
    assert len(runtime.calls) == 1
    names = [tool["function"]["name"] for tool in llm.tool_payloads[0]]
    assert "mcp__local__echo" in names
    dynamic = next(
        tool for tool in llm.tool_payloads[0]
        if tool["function"]["name"] == "mcp__local__echo"
    )
    assert dynamic["function"]["parameters"]["required"] == ["message"]
    assert "untrusted server metadata" in llm.calls[0][0]["content"]


def test_dynamic_argument_error_happens_before_hook_policy_approval_and_call(tmp_path) -> None:
    runtime = FakeRuntime()
    llm = ScriptedLLM([_mcp_action(args={}), _done("repaired")])
    approvals: list[str] = []
    events: list[dict] = []

    result = run_once(
        "call echo",
        llm,
        cwd=tmp_path,
        run_id="run_mcp_invalid_args",
        mcp_runtime=runtime,
        approval_handler=lambda action: approvals.append(action.action.name) or True,
        event_handler=events.append,
    )

    assert result.observations[0].error is not None
    assert result.observations[0].error.code == ErrorCode.MISSING_REQUIRED_FIELD
    assert runtime.calls == []
    assert approvals == []
    assert not any(event["event"] == "tool_start" for event in events)
    assert result.action.action.name == "done"


@pytest.mark.parametrize(
    "config, approval_outcome, expected_code, expected_status",
    [
        (
            AgentConfig(sandbox="read-only"),
            True,
            ErrorCode.POLICY_DENIED,
            "error",
        ),
        (
            AgentConfig(approval="never"),
            True,
            ErrorCode.POLICY_DENIED,
            "error",
        ),
        (
            AgentConfig(dry_run=True),
            True,
            None,
            "ok",
        ),
        (
            AgentConfig(),
            False,
            ErrorCode.APPROVAL_DENIED,
            "error",
        ),
        (
            AgentConfig(),
            "timed_out",
            ErrorCode.APPROVAL_DENIED,
            "error",
        ),
    ],
)
def test_policy_dry_run_and_approval_paths_never_call_mcp(
    tmp_path,
    config,
    approval_outcome,
    expected_code,
    expected_status,
) -> None:
    runtime = FakeRuntime()
    llm = ScriptedLLM([_mcp_action(), _done()])
    approvals: list[str] = []

    result = run_once(
        "call echo",
        llm,
        cwd=tmp_path,
        run_id=f"run_mcp_no_call_{expected_status}_{config.approval}_{config.sandbox}_{config.dry_run}",
        config=config,
        mcp_runtime=runtime,
        approval_handler=lambda action: approvals.append(action.action.name) or approval_outcome,
    )

    first = result.observations[0]
    assert first.status == expected_status
    assert runtime.calls == []
    if expected_code is not None:
        assert first.error is not None
        assert first.error.code == expected_code
    if config.dry_run or config.sandbox == "read-only" or config.approval == "never":
        assert approvals == []


def test_missing_approval_handler_does_not_call_mcp(tmp_path) -> None:
    runtime = FakeRuntime()
    result = run_once(
        "call echo",
        ScriptedLLM([_mcp_action()]),
        cwd=tmp_path,
        run_id="run_mcp_approval_required",
        mcp_runtime=runtime,
    )

    assert runtime.calls == []
    assert result.observation.error is not None
    assert result.observation.error.code == ErrorCode.APPROVAL_REQUIRED


def test_doc_research_denies_mcp_while_exact_and_empty_allowlists_allow_it(tmp_path) -> None:
    denied_runtime = FakeRuntime()
    denied = run_once(
        "call echo",
        ScriptedLLM([_mcp_action(), _done()]),
        cwd=tmp_path,
        run_id="run_mcp_doc_deny",
        selected_skills=["doc-research"],
        mcp_runtime=denied_runtime,
        approval_handler=lambda _action: True,
    )
    assert denied.observations[0].error is not None
    assert denied.observations[0].error.code == ErrorCode.POLICY_DENIED
    assert denied_runtime.calls == []

    for skill_name, allowed_block in [
        ("exact", "  - mcp__local__echo\n"),
        ("open", ""),
    ]:
        skill_dir = tmp_path / ".agent" / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {skill_name}\n"
            "description: MCP test skill\n"
            "allowed_tools:\n"
            f"{allowed_block}"
            "---\n"
            "Use the configured tool.\n",
            encoding="utf-8",
        )
        runtime = FakeRuntime()
        result = run_once(
            "call echo",
            ScriptedLLM([_mcp_action(), _done()]),
            cwd=tmp_path,
            run_id=f"run_mcp_skill_{skill_name}",
            selected_skills=[skill_name],
            mcp_runtime=runtime,
            approval_handler=lambda _action: True,
        )
        assert result.observations[0].status == "ok"
        assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    "status, expected_code",
    [
        ("tool_error", ErrorCode.TOOL_FAILED),
        ("timeout", ErrorCode.TIMEOUT),
        ("failed", ErrorCode.TOOL_FAILED),
    ],
)
def test_mcp_result_status_maps_into_existing_recovery_loop(
    tmp_path,
    status,
    expected_code,
) -> None:
    runtime = FakeRuntime(
        results=[
            McpCallResult(
                status=status,
                summary=f"{status} result",
                diagnostic_details={"stage": status},
            )
        ]
    )
    result = run_once(
        "call echo",
        ScriptedLLM([_mcp_action(), _done("recovered")]),
        cwd=tmp_path,
        run_id=f"run_mcp_status_{status}",
        mcp_runtime=runtime,
        approval_handler=lambda _action: True,
    )

    first = result.observations[0]
    assert first.error is not None
    assert first.error.code == expected_code
    assert first.error.details["source"] == "mcp"
    assert first.error.details["server_id"] == "local"
    assert first.error.details["remote_tool"] == "echo"
    assert result.action.action.name == "done"


def test_adapter_redaction_count_merges_with_live_and_durable_redaction(tmp_path) -> None:
    secret = "sk-mcp-loop-secret-f83a"
    runtime = FakeRuntime(
        results=[
            McpCallResult(
                status="ok",
                summary="safe [REDACTED]",
                data={"value": "[REDACTED]"},
                redaction_replacements=2,
            )
        ]
    )
    result = run_once(
        "call echo",
        ScriptedLLM([_mcp_action(secret), _done()]),
        cwd=tmp_path,
        run_id="run_mcp_redaction",
        mcp_runtime=runtime,
        approval_handler=lambda _action: True,
    )

    text = result.tool_calls_path.read_text(encoding="utf-8")
    assert secret not in text
    first = json.loads(text.splitlines()[0])
    assert first["redaction"]["replacements"] == 3
    assert first["observation"]["data"]["result"]["value"] == "[REDACTED]"
    assert runtime.calls[0][1] == {"message": secret}


@pytest.mark.parametrize("native", [False, True])
def test_mcp_model_payload_budget_fails_before_model_call(tmp_path, native: bool) -> None:
    definitions = tuple(
        _definition(
            f"mcp__local__payload_{index}",
            remote_name=f"payload_{index}",
            padding=44 * 1024,
        )
        for index in range(3)
    )
    runtime = FakeRuntime(definitions=definitions)
    llm = ScriptedNativeLLM([_done()]) if native else ScriptedLLM([_done()])

    with pytest.raises(ToolCatalogError, match="128 KiB"):
        run_once(
            "must fail before model",
            llm,
            cwd=tmp_path,
            run_id=f"run_mcp_payload_{native}",
            config=AgentConfig(native_tools=native),
            mcp_runtime=runtime,
        )

    assert runtime.discover_calls == 1
    assert llm.calls == []
