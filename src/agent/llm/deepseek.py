from __future__ import annotations

from agent.llm.openai_compat import (
    OpenAICompatClient,
    ProviderError,
    RetrySleep,
    SmokeResult,
    StreamTransport,
    Transport,
    smoke_provider,
)

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

DeepSeekError = ProviderError
DeepSeekSmokeResult = SmokeResult


class DeepSeekClient(OpenAICompatClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        timeout: float = 60.0,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        retry_sleep: RetrySleep | None = None,
    ) -> None:
        if not api_key.strip():
            raise DeepSeekError("DeepSeek API key is required.")
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_label="DeepSeek",
            timeout=timeout,
            transport=transport,
            stream_transport=stream_transport,
            retry_sleep=retry_sleep,
        )


def smoke_deepseek_provider(
    *,
    api_key: str,
    model: str = DEFAULT_DEEPSEEK_MODEL,
    api_key_env: str = "DEEPSEEK_API_KEY",
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> DeepSeekSmokeResult:
    if not api_key.strip():
        raise DeepSeekError("DeepSeek API key is required.")
    return smoke_provider(
        provider_name="deepseek",
        api_key=api_key,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        provider_label="DeepSeek",
        timeout=timeout,
        transport=transport,
    )
