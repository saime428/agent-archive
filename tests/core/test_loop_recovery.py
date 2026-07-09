from __future__ import annotations

from agent.config import AgentConfig
from agent.core.actions import ErrorCode
from agent.core.loop import run_once


class ScriptedLLM:
    """按脚本依次返回动作,并记录每次调用收到的消息列表。"""

    def __init__(self, actions: list[dict]) -> None:
        self.actions = actions
        self.messages_by_call: list[list[dict]] = []
        self._index = 0

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        self.messages_by_call.append([dict(message) for message in messages])
        if self._index >= len(self.actions):
            raise AssertionError("ScriptedLLM ran out of responses.")
        action = self.actions[self._index]
        self._index += 1
        return action


def _read_missing(message: str = "Read a file.") -> dict:
    return {
        "message": message,
        "action": {"name": "read_file", "args": {"path": "missing.txt"}},
    }


def _list_dir() -> dict:
    return {
        "message": "List workspace.",
        "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 5}},
    }


def _done(final: str = "Recovered.") -> dict:
    return {
        "message": "Done.",
        "action": {
            "name": "done",
            "args": {"final": final, "changed_files": [], "next_steps": []},
        },
    }


def _write_notes() -> dict:
    return {
        "message": "Write notes.",
        "action": {
            "name": "write_file",
            "args": {"path": "notes.txt", "content": "hello\n", "create_parents": False},
        },
    }


def test_recoverable_error_feeds_back_and_run_recovers(tmp_path) -> None:
    llm = ScriptedLLM([_read_missing(), _done()])

    result = run_once("read missing file", llm, cwd=tmp_path, run_id="run_recover")

    assert result.observations[0].status == "error"
    assert result.observations[0].error is not None
    assert result.observations[0].error.code == ErrorCode.TOOL_FAILED
    assert result.action.action.name == "done"
    assert result.observation.status == "ok"

    second_call = llm.messages_by_call[1]
    feedback = next(
        message["content"]
        for message in second_call
        if "UNTRUSTED TOOL OBSERVATION" in message["content"]
    )
    assert "Error code: TOOL_FAILED" in feedback
    assert "Do not repeat the same action with identical args" in feedback


def test_consecutive_errors_exhaust_budget(tmp_path) -> None:
    llm = ScriptedLLM([_read_missing(f"Attempt {i}.") for i in range(1, 4)])
    config = AgentConfig(mode="auto")

    result = run_once("read missing file", llm, cwd=tmp_path, run_id="run_exhaust", config=config)

    assert len(result.observations) == 3
    assert result.observation.status == "error"
    assert result.observation.error is not None
    assert result.observation.error.details is not None
    assert result.observation.error.details["consecutive_errors_exhausted"] is True
    assert result.observation.error.details["consecutive_errors"] == 3


def test_success_resets_consecutive_error_counter(tmp_path) -> None:
    llm = ScriptedLLM(
        [
            _read_missing("Attempt 1."),
            _list_dir(),
            _read_missing("Attempt 2."),
            _read_missing("Attempt 3."),
            _done(),
        ]
    )
    config = AgentConfig(mode="auto")

    result = run_once("poke around", llm, cwd=tmp_path, run_id="run_reset", config=config)

    assert result.action.action.name == "done"
    assert result.observation.status == "ok"
    statuses = [observation.status for observation in result.observations]
    assert statuses == ["error", "ok", "error", "error", "ok"]


def test_approval_denied_is_still_terminal(tmp_path) -> None:
    llm = ScriptedLLM([_write_notes()])

    result = run_once(
        "write notes",
        llm,
        cwd=tmp_path,
        run_id="run_denied",
        approval_handler=lambda _action: False,
    )

    assert len(result.observations) == 1
    assert result.observation.status == "error"
    assert result.observation.error is not None
    assert result.observation.error.code == ErrorCode.APPROVAL_DENIED
    assert len(llm.messages_by_call) == 1


def test_write_success_is_fed_back_to_model(tmp_path) -> None:
    llm = ScriptedLLM([_write_notes(), _done("Wrote notes.")])

    result = run_once(
        "write notes",
        llm,
        cwd=tmp_path,
        run_id="run_write_feedback",
        approval_handler=lambda _action: True,
    )

    assert result.observation.status == "ok"
    second_call = llm.messages_by_call[1]
    feedback = next(
        message["content"]
        for message in second_call
        if "UNTRUSTED TOOL OBSERVATION" in message["content"]
    )
    assert "write_file" in feedback
    assert "Error code:" not in feedback


def test_configured_error_budget_of_one_makes_first_error_terminal(tmp_path) -> None:
    llm = ScriptedLLM([_read_missing()])
    config = AgentConfig(max_consecutive_errors=1)

    result = run_once("read missing file", llm, cwd=tmp_path, run_id="run_budget_one", config=config)

    assert len(result.observations) == 1
    assert result.observation.status == "error"
    assert result.observation.error is not None
    assert result.observation.error.details is not None
    assert result.observation.error.details["consecutive_errors_exhausted"] is True
