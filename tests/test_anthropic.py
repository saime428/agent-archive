from __future__ import annotations

import json

import pytest
from urllib.error import HTTPError

from agent.config import AgentConfig
from agent.llm.anthropic import (
    ANTHROPIC_VERSION,
    AnthropicClient,
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_MAX_TOKENS,
    smoke_anthropic_provider,
)
from agent.llm.factory import PROVIDER_REGISTRY, make_llm
from agent.llm.openai_compat import ProviderError


class RecordingTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body.decode("utf-8"))})
        return self.response


def _messages_response(text: str) -> bytes:
    return json.dumps({"content": [{"type": "text", "text": text}]}).encode("utf-8")


def _done_content() -> str:
    return json.dumps(
        {
            "message": "Done.",
            "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
        }
    )


def test_chat_maps_request_onto_messages_api() -> None:
    transport = RecordingTransport(_messages_response(_done_content()))
    client = AnthropicClient(api_key="sk-a", model="claude-sonnet-5", transport=transport)

    result = client.chat(
        [
            {"role": "system", "content": "rule one"},
            {"role": "system", "content": "rule two"},
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "third"},
        ],
        temperature=0.2,
    )

    call = transport.calls[0]
    assert call["url"] == f"{DEFAULT_ANTHROPIC_BASE_URL}/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-a"
    assert call["headers"]["anthropic-version"] == ANTHROPIC_VERSION
    body = call["body"]
    assert body["model"] == "claude-sonnet-5"
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS
    assert body["temperature"] == 0.2
    assert body["system"] == "rule one\n\nrule two"
    assert body["messages"] == [
        {"role": "user", "content": "first\n\nsecond"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "third"},
    ]
    assert isinstance(result, dict)
    assert result["action"]["name"] == "done"


def test_empty_api_key_sends_no_key_header() -> None:
    transport = RecordingTransport(_messages_response("plain text"))
    client = AnthropicClient(api_key="", model="m", base_url="https://relay.example.com", transport=transport)

    result = client.chat([{"role": "user", "content": "hi"}])

    assert "x-api-key" not in transport.calls[0]["headers"]
    assert transport.calls[0]["url"] == "https://relay.example.com/v1/messages"
    assert result == "plain text"


def test_unsupported_role_rejected() -> None:
    transport = RecordingTransport(_messages_response("x"))
    client = AnthropicClient(api_key="", model="m", transport=transport)

    with pytest.raises(ProviderError, match="role"):
        client.chat([{"role": "tool", "content": "x"}])


def test_multiple_text_blocks_are_concatenated() -> None:
    response = json.dumps(
        {"content": [{"type": "text", "text": "hel"}, {"type": "thinking", "thinking": "…"}, {"type": "text", "text": "lo"}]}
    ).encode("utf-8")
    client = AnthropicClient(api_key="", model="m", transport=RecordingTransport(response))

    assert client.chat([{"role": "user", "content": "hi"}]) == "hello"


def test_retryable_status_is_retried() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        return _messages_response("ok")

    client = AnthropicClient(api_key="", model="m", transport=transport, retry_sleep=sleeps.append)

    assert client.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 2
    assert sleeps == [1.0]


def _sse(events: list[dict]) -> list[bytes]:
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}\n".encode("utf-8"))
        lines.append(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
    return lines


def test_stream_chat_yields_text_deltas_until_message_stop() -> None:
    events = [
        {"type": "message_start", "message": {}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hel"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]
    client = AnthropicClient(api_key="", model="m", stream_transport=lambda *args: iter(_sse(events)))

    assert list(client.stream_chat([{"role": "user", "content": "hi"}])) == ["hel", "lo"]


def test_stream_chat_error_event_raises_provider_error() -> None:
    events = [{"type": "error", "error": {"type": "overloaded_error", "message": "overloaded"}}]
    client = AnthropicClient(api_key="", model="m", stream_transport=lambda *args: iter(_sse(events)))

    with pytest.raises(ProviderError, match="overloaded"):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))


def test_smoke_provider_reports_ok() -> None:
    transport = RecordingTransport(_messages_response(_done_content()))

    result = smoke_anthropic_provider(
        api_key="sk-a",
        model="claude-sonnet-5",
        base_url=DEFAULT_ANTHROPIC_BASE_URL,
        api_key_env="ANTHROPIC_API_KEY",
        transport=transport,
    )

    assert result.provider == "anthropic"
    assert result.status == "ok"
    assert result.final == "ok"
    assert transport.calls[0]["body"]["temperature"] == 0


def test_factory_builds_anthropic_client_with_default_base_url(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
    config = AgentConfig(provider="anthropic", model="claude-sonnet-5", api_key_env="ANTHROPIC_API_KEY")

    llm = make_llm(config)

    assert isinstance(llm, AnthropicClient)
    assert llm.base_url == DEFAULT_ANTHROPIC_BASE_URL
    assert llm.api_key == "sk-a"
    spec = PROVIDER_REGISTRY["anthropic"]
    assert spec.capabilities.streaming is True
    assert spec.capabilities.native_tools is False


def test_factory_smoke_rejects_native_mode() -> None:
    config = AgentConfig(provider="anthropic", model="m")

    with pytest.raises(ProviderError, match="native"):
        PROVIDER_REGISTRY["anthropic"].smoke(config, True)
