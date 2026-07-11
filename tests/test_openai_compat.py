from __future__ import annotations

import json

import pytest

from agent.llm.openai_compat import OpenAICompatClient, ProviderError, smoke_provider, smoke_provider_native


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


def _tools_response(message_obj: dict) -> bytes:
    return json.dumps({"choices": [{"message": message_obj}]}).encode("utf-8")


def _done_tool_call(arguments: str) -> dict:
    return {
        "content": "Finishing.",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "done", "arguments": arguments}}
        ],
    }


DONE_ARGS = '{"final": "ok", "changed_files": [], "next_steps": []}'
TOOLS = [{"type": "function", "function": {"name": "done", "description": "d", "parameters": {"type": "object"}}}]


def test_chat_tools_sends_tools_and_required_choice() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call(DONE_ARGS)))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    envelope = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    body = transport.calls[0]["body"]
    assert body["tools"] == TOOLS
    assert body["tool_choice"] == "required"
    assert body["stream"] is False
    assert envelope == {
        "message": "Finishing.",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }


def test_chat_tools_takes_first_of_multiple_tool_calls() -> None:
    message_obj = {
        "content": "",
        "tool_calls": [
            {"function": {"name": "done", "arguments": DONE_ARGS}},
            {"function": {"name": "read_file", "arguments": '{"path": "x"}'}},
        ],
    }
    transport = RecordingTransport(_tools_response(message_obj))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    envelope = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert envelope["action"]["name"] == "done"


def test_chat_tools_returns_raw_string_for_invalid_arguments_json() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call('{"final": broken')))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == '{"final": broken'


def test_chat_tools_returns_actionless_envelope_when_no_tool_call() -> None:
    transport = RecordingTransport(_tools_response({"content": "just chatting"}))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == {"message": "just chatting"}


def _sse(events: list[str]) -> list[bytes]:
    return [f"data: {event}\n".encode("utf-8") for event in events] + [b"data: [DONE]\n"]


def _drive(generator):
    chunks: list[str] = []
    while True:
        try:
            chunks.append(next(generator))
        except StopIteration as stop:
            return chunks, stop.value


def test_stream_chat_tools_assembles_fragmented_tool_call() -> None:
    events = [
        '{"choices": [{"delta": {"content": "Think"}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "done", "arguments": ""}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\\"final\\": \\"o"}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "k\\", \\"changed_files\\": [], \\"next_steps\\": []}"}}]}}]}',
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert "Think" in "".join(chunks)
    assert '"final"' in "".join(chunks)
    assert envelope == {
        "message": "Think",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }


def test_stream_chat_tools_requests_streaming_with_required_choice() -> None:
    captured: dict = {}

    def stream_transport(url, headers, body, timeout):
        captured["body"] = json.loads(body.decode("utf-8"))
        return iter(_sse(['{"choices": [{"delta": {"content": "x"}}]}']))

    client = OpenAICompatClient(
        api_key="", model="m", base_url="http://localhost:11434/v1", stream_transport=stream_transport
    )

    _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert captured["body"]["stream"] is True
    assert captured["body"]["tool_choice"] == "required"
    assert captured["body"]["tools"] == TOOLS


def test_stream_chat_tools_without_tool_call_returns_actionless_envelope() -> None:
    events = ['{"choices": [{"delta": {"content": "no tools here"}}]}']
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope == {"message": "no tools here"}


def test_stream_chat_tools_ignores_non_zero_indexes() -> None:
    events = [
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "done", "arguments": ""}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"name": "read_file", "arguments": "{}"}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "' + DONE_ARGS.replace('"', '\\"') + '"}}]}}]}',
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope["action"]["name"] == "done"


def test_stream_chat_tools_reports_invalid_sse() -> None:
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter([b"not sse\n"]),
    )

    with pytest.raises(ProviderError):
        _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))


def test_smoke_provider_native_validates_done_tool_call() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call('{"final": "smoke ok", "changed_files": [], "next_steps": []}')))

    result = smoke_provider_native(
        provider_name="openai-compat",
        api_key="",
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key_env="OPENAI_API_KEY",
        provider_label="openai-compat",
        transport=transport,
    )

    assert result.status == "ok"
    assert result.final == "smoke ok"
    body = transport.calls[0]["body"]
    assert body["tool_choice"] == "required"
    assert [tool["function"]["name"] for tool in body["tools"]] == ["done"]
