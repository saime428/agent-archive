from __future__ import annotations

import pytest

from agent.config import AgentConfig
from agent.llm.deepseek import DeepSeekClient
from agent.llm.factory import PROVIDER_REGISTRY, make_llm
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient, ProviderError


def test_provider_registry_contains_builtin_providers() -> None:
    assert set(PROVIDER_REGISTRY) == {"fake", "deepseek", "openai-compat"}


def test_make_llm_uses_provider_registry(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")

    fake = make_llm(AgentConfig(provider="fake"))
    deepseek = make_llm(AgentConfig(provider="deepseek", model="deepseek-v4-flash"))

    assert isinstance(fake, FakeLLMClient)
    assert isinstance(deepseek, DeepSeekClient)
    assert deepseek.model == "deepseek-v4-flash"


def test_make_llm_builds_openai_compat_client(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    config = AgentConfig(provider="openai-compat", model="llama3", base_url="http://localhost:11434/v1")

    client = make_llm(config)

    assert isinstance(client, OpenAICompatClient)
    assert client.base_url == "http://localhost:11434/v1"
    assert client.api_key == ""


def test_make_llm_openai_compat_requires_base_url() -> None:
    config = AgentConfig(provider="openai-compat", model="llama3")

    with pytest.raises(ProviderError):
        make_llm(config)
