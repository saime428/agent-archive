from __future__ import annotations

from agent.config import AgentConfig
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


def _capability_events(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("event") == "capability_warning"]


def test_native_tools_mismatch_emits_single_warning_and_downgrades(tmp_path) -> None:
    events: list[dict] = []

    result = run_once(
        "finish",
        FakeLLMClient(),
        cwd=tmp_path,
        config=AgentConfig(native_tools=True),
        event_handler=events.append,
    )

    warnings = _capability_events(events)
    assert len(warnings) == 1
    assert warnings[0]["requested"] == "native_tools"
    assert warnings[0]["fallback"] == "json-protocol"
    assert warnings[0]["run_id"] == result.context.run_id
    assert result.observation.status == "ok"


def test_matched_capabilities_emit_no_warning(tmp_path) -> None:
    events: list[dict] = []

    run_once(
        "finish",
        FakeLLMClient(),
        cwd=tmp_path,
        config=AgentConfig(),
        event_handler=events.append,
    )

    assert _capability_events(events) == []


def test_capable_double_with_native_config_emits_no_warning(tmp_path) -> None:
    class NativeDouble:
        def chat(self, messages, *, temperature=None):
            return {}

        def chat_tools(self, messages, tools, *, temperature=None):
            return {
                "message": "",
                "action": {
                    "name": "done",
                    "args": {"final": "ok", "changed_files": [], "next_steps": []},
                },
            }

    events: list[dict] = []

    run_once(
        "finish",
        NativeDouble(),
        cwd=tmp_path,
        config=AgentConfig(native_tools=True),
        event_handler=events.append,
    )

    assert _capability_events(events) == []
