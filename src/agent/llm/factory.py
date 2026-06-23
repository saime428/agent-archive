from __future__ import annotations

import os

from agent.config import AgentConfig
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient


def make_llm(config: AgentConfig):
    if config.provider == "fake":
        return FakeLLMClient()
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)
