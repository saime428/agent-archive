from __future__ import annotations

import os
from collections.abc import Callable

from agent.config import AgentConfig
from agent.llm.base import LLMClient
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient, ProviderError


def _make_deepseek(config: AgentConfig) -> DeepSeekClient:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)


def _make_openai_compat(config: AgentConfig) -> OpenAICompatClient:
    if not config.base_url.strip():
        raise ProviderError("openai-compat provider requires base