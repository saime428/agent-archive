from __future__ import annotations

import pytest

from agent.config import AgentConfig
from agent.llm.deepseek import DeepSeekClient
from agent.llm.factory import PROVIDER_REGISTRY, make_llm
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient, ProviderError


def test_provider_registry_contains_builtin_providers() -> None:
    assert set(PROVIDER_REGISTRY) == {"fake", "deepseek"}


def test_make_llm_uses_provider_registry(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    fake = make_llm(AgentConfig(provider="fake"))
    deepseek = make_llm(AgentConfig(provider="deepseek", model="deepseek-v4-flash"))

    assert isinstance(fake, FakeLLMClient)
    assert i