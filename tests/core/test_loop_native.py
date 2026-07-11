from __future__ import annotations

from agent.config import AgentConfig
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


def _done_envelope(final: str = "native done") -> dict:
    return {
        "message": "Finishing.",
        "action": {"name": "done", "args": {"final": final, "changed_files": [], "next_steps": []}},
    }


def _read_missing_envelope() -> dict:
    return {"message": "Reading.", "action": {"name": "read_file", "args": {"path": "missing.txt"}}}


class ScriptedNativeLLM:
    """chat_tools 按脚本返回;记录每次调用的 messages 与 tools。"""

    def __init__(self, responses: list[dict | str]) -> None:
        self.responses = responses
        self.calls: list[dict] = []
        self._index = 0

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        raise AssertionError("JSON-protocol chat must not be used when native tools are active.")

    def chat_tools(self, messages: list[dict], tools: list[dict], *, temperature: float | None = None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if self._index >= len(self.responses):
            raise AssertionError("ScriptedNativeLLM ran out of responses.")
        response = self.responses[self._index]
        self._index += 1
        return response


def test_native_run_uses_chat_tools_and_completes(tmp_path) -> None:
    llm = ScriptedNativeLLM([_done_envelope()])
    config = AgentConfig(native_tools=True)

    result = run_once("say done", llm, cwd=tmp_path, run_id="run_native", config=config)

    assert result.action.action.name == "done"
    assert result.observation.data == {"final": "native done"}
    tools = llm.calls[0]["tools"]
    tool_names = [tool["function"]["name"] for tool in tools]
    assert tool_names[0] == "done"
    assert "read_file" in tool_names
    system = llm.calls[0]["messages"][0]["content"]
    assert "Call exactly one tool" in system
    assert "JSON action object" not in system


def test_native_hides_web_search_tool_when_disabled(tmp_path) -> None:
    llm = ScriptedNativeLLM([_done_envelope()])
    config = AgentConfig(native_tools=True, web_search_enabled=False)

    run_once("say done", llm, cwd=tmp_path, run_id="run_native_ws", config=config)

    tool_names = [tool["function"]["name"] for tool in llm.calls[0]["tools"]]
    assert "web_search" not in tool_names


def test_native_actionless_response_routes_to_repair(tmp_path) -> None:
    llm = ScriptedNativeLLM([{"message": "just chatting"}, _done_envelope("recovered")])
    config = AgentConfig(native_tools=True)

    result = run_once("say done", llm, cwd=tmp_path, run_id="run_native_repair", config=config)

    assert result.action.action.name == "done"
    assert result.observation.data == {"final": "recovered"}
    repair = llm.calls[1]["messages"][-1]["content"]
    assert "Call exactly one tool" in repair


def test_native_error_recovery_still_works(tmp_path) -> None:
    llm = ScriptedNativeLLM([_read_missing_envelope(), _done_envelope("recovered from error")])
    config = AgentConfig(native_tools=True)

    result = run_once("read missing file", llm, cwd=tmp_path, run_id="run_native_recover", config=config)

    assert result.observations[0].status == "error"
    assert result.action.action.name == "done"
    feedback = next(
        message["content"]
        for message in llm.calls[1]["messages"]
        if "UNTRUSTED TOOL OBSERVATION" in message["content"]
    )
    assert "Error code: TOOL_FAILED" in feedback


def test_native_flag_falls_back_to_json_protocol_without_chat_tools(tmp_path) -> None:
    config = AgentConfig(native_tools=True)

    result = run_once("inspect project", FakeLLMClient(), cwd=tmp_path, run_id="run_native_fallback", config=config)

    assert result.action.action.name == "done"
    assert result.observation.status == "ok"
