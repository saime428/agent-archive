from __future__ import annotations

from typing import Any

from agent.llm.base import ProviderCapabilities


class FakeLLMClient:
    capabilities = ProviderCapabilities(streaming=False, native_tools=False, reasoning=False)

    def __init__(
        self,
        *,
        actions: list[dict[str, Any]] | None = None,
        include_fake_metadata: bool = False,
    ) -> None:
        self.actions = actions or []
        self.include_fake_metadata = include_fake_metadata
        self._index = 0

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if self._index < len(self.actions):
            action = self.actions[self._index]
            self._index += 1
            return action

        task = _extract_task(messages)
        final = _common_answer(task) or f"FakeLLM received task: {task}"
        response: dict[str, Any] = {
            "message": "Task completed by FakeLLM.",
            "action": {
                "name": "done",
                "args": {
                    "final": final,
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


def _common_answer(task: str) -> str | None:
    text = task.strip().lower()
    if text in {"你好", "hello", "hi"}:
        return "你好，我在。你可以直接告诉我要看哪个文件、改什么代码，或者让我检查当前项目。"
    if "你是谁" in task:
        return "我是这个本地 Agent Workbench 里的代码助手，负责帮你读项目、改文件、跑命令、看 diff 和整理结果。"
    if "什么模型" in task or "哪个模型" in task:
        return "我会按当前工作区配置调用模型；如果 provider 是 DeepSeek，就走 DeepSeek 模型，离线测试时才用 FakeLLM 占位。"
    if "能做什么" in task or "可以做什么" in task:
        return "我可以帮你检查项目、读写文件、搜索代码、生成 patch、查看 Git 状态和 diff、运行命令，并把过程和结果留在本地 run 记录里。"
    return None
