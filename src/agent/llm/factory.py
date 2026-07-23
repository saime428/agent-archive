from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from agent.config import AgentConfig
from agent.llm.base import LLMClient, ProviderCapabilities
from agent.llm.deepseek import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DeepSeekClient,
    smoke_deepseek_provider,
)
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import (
    OpenAICompatClient,
    ProviderError,
    SmokeResult,
    smoke_provider,
    smoke_provider_native,
)


def _make_deepseek(config: AgentConfig) -> DeepSeekClient:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)


def _make_openai_compat(config: AgentConfig) -> OpenAICompatClient:
    if not config.base_url.strip():
        raise ProviderError("openai-compat provider requires base_url in .agent/config.toml.")
    api_key = os.environ.get(config.api_key_env, "")
    return OpenAICompatClient(
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        provider_label="openai-compat",
    )


def _smoke_deepseek(config: AgentConfig, native: bool) -> SmokeResult:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    if not api_key:
        raise ProviderError(f"DeepSeek API key is required in {config.deepseek_api_key_env}.")
    if native:
        return smoke_provider_native(
            provider_name="deepseek",
            api_key=api_key,
            model=config.model,
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            api_key_env=config.deepseek_api_key_env,
            provider_label="DeepSeek",
        )
    return smoke_deepseek_provider(
        api_key=api_key,
        model=config.model,
        api_key_env=config.deepseek_api_key_env,
    )


def _smoke_openai_compat(config: AgentConfig, native: bool) -> SmokeResult:
    if not config.base_url.strip():
        raise ProviderError("openai-compat smoke requires base_url in .agent/config.toml.")
    api_key = os.environ.get(config.api_key_env, "")
    if native:
        return smoke_provider_native(
            provider_name="openai-compat",
            api_key=api_key,
            model=config.model,
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            provider_label="openai-compat",
        )
    return smoke_provider(
        provider_name="openai-compat",
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        api_key_env=config.api_key_env,
        provider_label="openai-compat",
    )


@dataclass(frozen=True)
class ProviderSpec:
    factory: Callable[[AgentConfig], LLMClient]
    capabilities: ProviderCapabilities
    api_key_env: Callable[[AgentConfig], str] | None
    requires_base_url: bool
    smoke: Callable[[AgentConfig, bool], SmokeResult] | None


PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    "fake": ProviderSpec(
        factory=lambda _config: FakeLLMClient(),
        capabilities=FakeLLMClient.capabilities,
        api_key_env=None,
        requires_base_url=False,
        smoke=None,
    ),
    "deepseek": ProviderSpec(
        factory=_make_deepseek,
        capabilities=DeepSeekClient.capabilities,
        api_key_env=lambda config: config.deepseek_api_key_env,
        requires_base_url=False,
        smoke=_smoke_deepseek,
    ),
    "openai-compat": ProviderSpec(
        factory=_make_openai_compat,
        capabilities=OpenAICompatClient.capabilities,
        api_key_env=lambda config: config.api_key_env,
        requires_base_url=True,
        smoke=_smoke_openai_compat,
    ),
}


def make_llm(config: AgentConfig):
    return PROVIDER_REGISTRY[config.provider].factory(config)
