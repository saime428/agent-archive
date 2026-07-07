from __future__ import annotations

import os
from collections.abc import Callable

from agent.config import AgentConfig
from agent.llm.base import LLMClient
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient


def _make_deepseek(config: AgentConfig) -> DeepSeekClient:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)


PROVIDER_REGISTRY: dict[str, Callable[[AgentConfig], LLMClient]] = {
    "fake": lambda _config: FakeLLMClient(),
    "deepseek": _make_deepseek,
}


def make_llm(config: AgentConfig):
    return PROVIDER_REGISTRY[config.provider](config)
