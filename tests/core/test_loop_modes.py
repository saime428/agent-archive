from __future__ import annotations

from agent.config import AgentConfig
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


class SpyLLMMode:
    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        self.messages = list(messages)
        return {
            "message": "Done.",
            "action": {
                "name": "done",
                "args": {"final": "ok", "changed_files": [], "next_steps": []},
            },
        }


def test_mode_guided_is_default_when_not_specified(tmp_path) -> None:
    result = run_once("test", FakeLLMClient(), cwd=tmp_path, run_id="run_default_mode")

    assert result.observation.status == "ok"


def test_mode_step_stops_after_one_iteration(tmp_path) -> None:
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "final answer", "changed_files": [], "next_steps": []},
                },
            },
        ]
    )
    config = AgentConfig(mode="step")

    result = run_once("test", llm, cwd=tmp_path, run_id="run_step_mode", config=config)

    assert result.observation.status == "ok"
    assert result.action.action.name == "done"
    assert len(result.observations) == 1
    assert result.observation.data == {"final": "final answer"}


def test_mode_auto_allows_more_iterations(tmp_path) -> None:
    actions = []
    for i in range(5):
        actions.append(
            {
                "message": f"Step {i + 1}.",
                "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 3}},
            }
        )
    actions.append(
        {
            "message": "Done.",
            "action": {"name": "done", "args": {"final": "done", "changed_files": [], "next_steps": []}},
        }
    )
    llm = FakeLLMClient(actions=actions)
    config = AgentConfig(mode="auto")

    result = run_once("test", llm, cwd=tmp_path, run_id="run_auto_mode", config=config)

    assert result.observation.status == "ok"
    assert result.action.action.name == "done"
    assert len(result.observations) == 6


def test_mode_auto_prompt_requires_sequential_actions_across_turns(tmp_path) -> None:
    llm = SpyLLMMode()

    run_once("test", llm, cwd=tmp_path, run_id="run_auto_prompt", config=AgentConfig(mode="auto"))

    system = next(message["content"] for message in llm.messages if message["role"] == "system")
    assert "multiple sequential actions across turns" in system
    assert "may use multiple tool calls" not in system


def test_mode_plan_first_adds_plan_instruction(tmp_path) -> None:
    llm = SpyLLMMode()
    config = AgentConfig(mode="plan-first")

    result = run_once("test", llm, cwd=tmp_path, run_id="run_plan_mode", config=config)

    assert result.observation.status == "ok"
    system_messages = [m for m in llm.messages if m["role"] == "system"]
    assert len(system_messages) == 1
    assert "Plan-first mode" in system_messages[0]["content"]


def test_explicit_max_iterations_overrides_mode(tmp_path) -> None:
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Done.",
                "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
            },
        ]
    )
    config = AgentConfig(mode="auto")

    result = run_once("test", llm, cwd=tmp_path, run_id="run_explicit_max", config=config, max_iterations=1)

    assert result.observation.status == "ok"
    assert result.action.action.name == "done"
    assert len(result.observations) == 1


def test_mode_guided_has_no_extra_prompt_instruction(tmp_path) -> None:
    llm = SpyLLMMode()
    config = AgentConfig(mode="guided")

    result = run_once("test", llm, cwd=tmp_path, run_id="run_guided_mode", config=config)

    assert result.observation.status == "ok"
    system_messages = [m for m in llm.messages if m["role"] == "system"]
    assert len(system_messages) == 1
    assert "Step mode" not in system_messages[0]["content"]
    assert "Auto mode" not in system_messages[0]["content"]
    assert "Plan-first mode" not in system_messages[0]["content"]
