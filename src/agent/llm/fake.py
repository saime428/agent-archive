from __future__ import annotations

from typing import Any


class FakeLLMClient:
    def __init__(self, *, include_fake_metadata: bool = False) -> None:
        self.include_fake_metadata = include_fake_metadata

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        task = _extract_task(messages)
        response: dict[str, Any] = {
            "message": "Task completed by FakeLLM.",
            "action": {
                "name": "done",
                "args": {
                    "final": f"FakeLLM received task: {task}",
                    "changed_files": [],
                    "next_steps": [],
                },
            },
        }
        if self.include_fake_metadata:
            response.update(
                {
                    "protocol_version": "fake-protocol",
                    "run_id": "model_run",
                    "action_id": "model_action",
                    "created_at": "1999-01-01T00:00:00Z",
                }
            )
        return response


def _extract_task(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""
