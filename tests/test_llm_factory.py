from __future__ import annotations

import pytest

from agent.config import VALID_VALUES, AgentConfig
from agent.llm.deepseek import DeepSeekClient
from agent.llm.factory import PROVIDER_REGISTRY, make_llm
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient, ProviderError, SmokeResult


def test_provider_registry_contains_builtin_providers() -> None:
    assert set(PROVIDER_REGISTRY) == VALID_VALUES["provider"]


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


def _smoke_result(provider: str) -> SmokeResult:
    return SmokeResult(
        provider=provider,
        model="m",
        api_key_env="E",
        status="ok",
        action_name="done",
        final="smoke ok",
    )


@pytest.mark.parametrize("name", sorted({"fake", "deepseek", "openai-compat"}))
def test_declared_capabilities_match_methods(name, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    config = AgentConfig(provider=name, base_url="http://localhost:9/v1")
    spec = PROVIDER_REGISTRY[name]
    client = spec.factory(config)
    caps = spec.capabilities
    assert caps is type(client).capabilities
    assert caps.native_tools == callable(getattr(client, "chat_tools", None))
    if caps.streaming:
        assert callable(getattr(client, "stream_chat", None))
        if caps.native_tools:
            assert callable(getattr(client, "stream_chat_tools", None))
    else:
        assert not callable(getattr(client, "stream_chat", None))


def test_fake_spec_has_no_auth_and_no_smoke() -> None:
    spec = PROVIDER_REGISTRY["fake"]
    assert spec.api_key_env is None
    assert spec.requires_base_url is False
    assert spec.smoke is None


def test_api_key_env_reads_provider_specific_config_field() -> None:
    config = AgentConfig(deepseek_api_key_env="DS_KEY", api_key_env="OA_KEY")
    assert PROVIDER_REGISTRY["deepseek"].api_key_env(config) == "DS_KEY"
    assert PROVIDER_REGISTRY["openai-compat"].api_key_env(config) == "OA_KEY"
    assert PROVIDER_REGISTRY["openai-compat"].requires_base_url is True


def test_deepseek_smoke_closure_wires_config(monkeypatch) -> None:
    calls = {}

    def fake_smoke(**kwargs):
        calls.update(kwargs)
        return _smoke_result("deepseek")

    monkeypatch.setenv("DS_KEY", "secret")
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)
    config = AgentConfig(provider="deepseek", model="deepseek-v4-flash", deepseek_api_key_env="DS_KEY")

    result = PROVIDER_REGISTRY["deepseek"].smoke(config, False)

    assert result.status == "ok"
    assert calls == {"api_key": "secret", "model": "deepseek-v4-flash", "api_key_env": "DS_KEY"}


def test_deepseek_smoke_closure_missing_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = AgentConfig(provider="deepseek")

    with pytest.raises(ProviderError) as excinfo:
        PROVIDER_REGISTRY["deepseek"].smoke(config, False)

    assert "DeepSeek API key is required in DEEPSEEK_API_KEY." in str(excinfo.value)


def test_deepseek_native_smoke_uses_default_base_url(monkeypatch) -> None:
    calls = {}

    def fake_native(**kwargs):
        calls.update(kwargs)
        return _smoke_result("deepseek")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr("agent.llm.factory.smoke_provider_native", fake_native)

    PROVIDER_REGISTRY["deepseek"].smoke(AgentConfig(provider="deepseek"), True)

    assert calls["provider_name"] == "deepseek"
    assert calls["base_url"] == "https://api.deepseek.com"
    assert calls["provider_label"] == "DeepSeek"


def test_openai_compat_smoke_closure_requires_base_url(monkeypatch) -> None:
    config = AgentConfig(provider="openai-compat")

    with pytest.raises(ProviderError) as excinfo:
        PROVIDER_REGISTRY["openai-compat"].smoke(config, False)

    assert "openai-compat smoke requires base_url in .agent/config.toml." in str(excinfo.value)


def test_openai_compat_smoke_closure_wires_config(monkeypatch) -> None:
    calls = {}

    def fake_smoke(**kwargs):
        calls.update(kwargs)
        return _smoke_result("openai-compat")

    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setattr("agent.llm.factory.smoke_provider", fake_smoke)
    config = AgentConfig(provider="openai-compat", model="llama3", base_url="http://localhost:11434/v1")

    PROVIDER_REGISTRY["openai-compat"].smoke(config, False)

    assert calls == {
        "provider_name": "openai-compat",
        "api_key": "oa-key",
        "model": "llama3",
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "OPENAI_API_KEY",
        "provider_label": "openai-compat",
    }
