from __future__ import annotations

import json

import pytest

from agent.llm.openai_compat import OpenAICompatClient, ProviderError, smoke_provider


class RecordingTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body.decode("utf-8"))})
        return self.response


def _chat_response(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _done_content() -> str:
    return json.dumps(
        {
            "message": "Done.",
            "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
        }
    )


def test_empty_api_key_sends_no_authorization_header() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))
    client = OpenAICompatClient(api_key="", model="llama3", base_url="http://localhost:11434/v1", transport=transport)

    client.chat([{"role": "user", "content": "hi"}])

    assert "Authorization" not in transport.calls[0]["headers"]
    assert transport.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"


def test_non_empty_api_key_sends_bearer_header() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))
    client = OpenAICompatClient(api_key="sk-x", model="m", base_url="https://api.example.com", transport=transport)

    client.chat([{"role": "user", "content": "hi"}])

    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-x"


def test_missing_base_url_rejected() -> None:
    with pytest.raises(ProviderError):
        OpenAICompatClient(api_key="", model="m", base_url=" ")


def test_missing_model_rejected() -> None:
    with pytest.raises(ProviderError):
        OpenAICompatClient(api_key="", model=" ", base_url="http://localhost:11434/v1")


def test_error_message_uses_provider_label() -> None:
    def failing_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        from urllib.error import URLError

        raise URLError("connection refused")

    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        provider_label="openai-compat",
        transport=failing_transport,
        retry_sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])

    assert "openai-compat API request failed" in str(excinfo.value)


def test_smoke_provider_returns_result_with_provider_name() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))

    result = smoke_provider(
        provider_name="openai-compat",
        api_key="",
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key_env="OPENAI_API_KEY",
        provider_label="openai-compat",
        transport=transport,
    )

    assert result.provider == "openai-compat"
    assert result.status == "ok"
    assert result.action_name == "done"
