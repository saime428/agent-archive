from __future__ import annotations

import json

import pytest

from agent.llm.openai_compat import (
    IGNORED_TOOL_CALLS_WARNING,
    OpenAICompatClient,
    ProviderError,
    _ReusableHTTPTransport,
    smoke_provider,
    smoke_provider_native,
)


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


def test_chat_tools_sends_tools_and_auto_choice() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call(DONE_ARGS)))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    envelope = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    body = transport.calls[0]["body"]
    assert body["tools"] == TOOLS
    assert body["tool_choice"] == "auto"
    assert body["stream"] is False
    assert envelope == {
        "message": "Finishing.",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }
    assert "_agent_warning" not in envelope


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

    assert envelope == {
        "message": "",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
        "_agent_warning": IGNORED_TOOL_CALLS_WARNING,
    }
    assert list(envelope).count("_agent_warning") == 1
    assert "read_file" not in repr(envelope)
    assert "path" not in envelope["action"]["args"]


def test_chat_tools_returns_raw_string_for_invalid_arguments_json() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call('{"final": broken')))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == '{"final": broken'


@pytest.mark.parametrize("arguments", ["", " \t\r\n"])
def test_chat_tools_treats_blank_arguments_as_empty_object(arguments: str) -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call(arguments)))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == {
        "message": "Finishing.",
        "action": {"name": "done", "args": {}},
    }


def test_chat_tools_invalid_first_call_with_extra_call_keeps_raw_repair_input() -> None:
    invalid_arguments = '{"final": broken'
    message_obj = {
        "content": "Finishing.",
        "tool_calls": [
            {"function": {"name": "done", "arguments": invalid_arguments}},
            {"function": {"name": "read_file", "arguments": '{"path": "secret.txt"}'}},
        ],
    }
    transport = RecordingTransport(_tools_response(message_obj))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == invalid_arguments


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

    text = "".join(part for _kind, part in chunks)
    assert "Think" in text
    assert '"final"' in text
    assert ("content", "Think") in chunks
    assert {kind for kind, _part in chunks} == {"content", "args"}
    assert envelope == {
        "message": "Think",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }
    assert "_agent_warning" not in envelope


def test_stream_chat_tools_requests_streaming_with_auto_choice() -> None:
    captured: dict = {}

    def stream_transport(url, headers, body, timeout):
        captured["body"] = json.loads(body.decode("utf-8"))
        return iter(_sse(['{"choices": [{"delta": {"content": "x"}}]}']))

    client = OpenAICompatClient(
        api_key="", model="m", base_url="http://localhost:11434/v1", stream_transport=stream_transport
    )

    _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert captured["body"]["stream"] is True
    assert captured["body"]["tool_choice"] == "auto"
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


def test_stream_chat_tools_treats_empty_arguments_as_empty_object() -> None:
    events = [
        json.dumps(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "done", "arguments": ""}}]}}]}
        )
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope == {"message": "", "action": {"name": "done", "args": {}}}


def test_stream_chat_tools_ignores_non_zero_indexes() -> None:
    events = [
        json.dumps(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "done", "arguments": ""}}]}}]}
        ),
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 1, "function": {"name": "read_file", "arguments": '{"path": "'}}
                            ]
                        }
                    }
                ]
            }
        ),
        json.dumps(
            {"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"arguments": 'secret.txt"}'}}]}}]}
        ),
        json.dumps(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": DONE_ARGS}}]}}]}
        ),
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope == {
        "message": "",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
        "_agent_warning": IGNORED_TOOL_CALLS_WARNING,
    }
    assert list(envelope).count("_agent_warning") == 1
    assert "secret.txt" not in repr(envelope)
    assert "read_file" not in repr(envelope)
    assert "secret.txt" not in repr(chunks)


def test_stream_chat_tools_yields_reasoning_as_thinking() -> None:
    events = [
        '{"choices": [{"delta": {"reasoning_content": "let me think"}}]}',
        '{"choices": [{"delta": {"content": "ok"}}]}',
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert ("thinking", "let me think") in chunks
    assert ("content", "ok") in chunks
    assert envelope == {"message": "ok"}


def test_stream_chat_tools_closes_transport_stream_after_done() -> None:
    closed = {"value": False}

    def stream_transport(url, headers, body, timeout):
        def gen():
            try:
                yield from _sse(['{"choices": [{"delta": {"content": "x"}}]}'])
                yield b"data: must-not-be-consumed\n"
            finally:
                closed["value"] = True

        return gen()

    client = OpenAICompatClient(
        api_key="", model="m", base_url="http://localhost:11434/v1", stream_transport=stream_transport
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert closed["value"] is True
    assert envelope == {"message": "x"}


def test_reusable_transport_drops_connection_when_stream_abandoned() -> None:
    transport = _ReusableHTTPTransport()
    url = "http://localhost:11434/v1/chat/completions"
    key = ("http", "localhost", 11434)

    class FakeResponse:
        will_close = False

        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            yield b"data: [DONE]\n"
            yield b"data: leftover\n"

        def close(self) -> None:
            self.closed = True

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()
    connection = FakeConnection()
    transport._connections[key] = connection
    transport._request = lambda *args, **kwargs: response

    stream = transport.stream_bytes(url, {}, b"", 1.0)
    assert next(stream) == b"data: [DONE]\n"
    stream.close()

    assert response.closed is True
    assert key not in transport._connections
    assert connection.closed is True


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
    assert body["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in body["tools"]] == ["done"]
