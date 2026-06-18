from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from agent.core.actions import parse_model_action
from agent.llm.deepseek import DeepSeekClient, DeepSeekError, smoke_deepseek_provider


def test_deepseek_client_posts_openai_compatible_chat_request() -> None:
    calls = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        calls.append((url, headers, json.loads(body.decode("utf-8")), timeout))
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "Done.",
                                    "action": {
                                        "name": "done",
                                        "args": {"final": "ok", "changed_files": [], "next_steps": []},
                                    },
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    client = DeepSeekClient(api_key="secret", model="deepseek-v4-flash", transport=transport)

    response = client.chat([{"role": "user", "content": "finish"}], temperature=0.2)

    assert response["action"]["name"] == "done"
    assert calls == [
        (
            "https://api.deepseek.com/chat/completions",
            {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            {
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "finish"}],
                "temperature": 0.2,
                "stream": False,
            },
            60.0,
        )
    ]


def test_deepseek_client_rejects_missing_api_key() -> None:
    with pytest.raises(DeepSeekError) as exc_info:
        DeepSeekClient(api_key="")

    assert "API key is required" in str(exc_info.value)


def test_deepseek_client_returns_non_json_model_content_for_repair_loop() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode("utf-8")

    client = DeepSeekClient(api_key="secret", transport=transport)

    response = client.chat([{"role": "user", "content": "finish"}])

    assert response == "not json"


def test_deepseek_client_reports_http_errors() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)

    client = DeepSeekClient(api_key="secret", transport=transport)

    with pytest.raises(DeepSeekError) as exc_info:
        client.chat([{"role": "user", "content": "finish"}])

    assert "DeepSeek API request failed: 401 Unauthorized" in str(exc_info.value)


def test_deepseek_client_reports_network_errors() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        raise URLError("offline")

    client = DeepSeekClient(api_key="secret", transport=transport)

    with pytest.raises(DeepSeekError) as exc_info:
        client.chat([{"role": "user", "content": "finish"}])

    assert "DeepSeek API request failed" in str(exc_info.value)


def test_deepseek_client_streams_sse_delta_content() -> None:
    calls = []

    def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        calls.append((url, headers, json.loads(body.decode("utf-8")), timeout))
        yield b'data: {"choices":[{"delta":{"content":"{\\"message\\":\\"Done.\\","}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"\\"action\\":{\\"name\\":\\"done\\","}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"\\"args\\":{\\"final\\":\\"ok\\",\\"changed_files\\":[],\\"next_steps\\":[]}}}"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    client = DeepSeekClient(api_key="secret", model="deepseek-v4-flash", stream_transport=stream_transport)

    chunks = list(client.stream_chat([{"role": "user", "content": "finish"}], temperature=0))
    raw_action = "".join(chunks)
    action = parse_model_action(raw_action, run_id="run_stream", action_index=1, created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))

    assert action.action.name == "done"
    assert action.action.args["final"] == "ok"
    assert calls[0][0] == "https://api.deepseek.com/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer secret"
    assert calls[0][2]["stream"] is True
    assert calls[0][2]["temperature"] == 0


def test_deepseek_client_streaming_stops_on_done_marker() -> None:
    def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"
        yield b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n\n'

    client = DeepSeekClient(api_key="secret", stream_transport=stream_transport)

    assert list(client.stream_chat([{"role": "user", "content": "finish"}])) == ["hello"]


def test_deepseek_client_streaming_reports_invalid_sse() -> None:
    def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        yield b"data: {not json}\n\n"

    client = DeepSeekClient(api_key="secret", stream_transport=stream_transport)

    with pytest.raises(DeepSeekError) as exc_info:
        list(client.stream_chat([{"role": "user", "content": "finish"}]))

    assert "invalid streaming response" in str(exc_info.value)


def test_deepseek_client_streaming_reports_non_text_delta() -> None:
    def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        yield b'data: {"choices":[{"delta":{"content":123}}]}\n\n'

    client = DeepSeekClient(api_key="secret", stream_transport=stream_transport)

    with pytest.raises(DeepSeekError) as exc_info:
        list(client.stream_chat([{"role": "user", "content": "finish"}]))

    assert "non-text streaming content" in str(exc_info.value)


def test_deepseek_client_streaming_reports_http_errors() -> None:
    def stream_transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        yield b""

    client = DeepSeekClient(api_key="secret", stream_transport=stream_transport)

    with pytest.raises(DeepSeekError) as exc_info:
        list(client.stream_chat([{"role": "user", "content": "finish"}]))

    assert "DeepSeek API request failed: 429 Too Many Requests" in str(exc_info.value)


def test_deepseek_smoke_validates_done_action_without_running_tools() -> None:
    calls = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        payload = json.loads(body.decode("utf-8"))
        calls.append((url, headers, payload, timeout))
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "Smoke complete.",
                                    "action": {
                                        "name": "done",
                                        "args": {
                                            "final": "smoke ok",
                                            "changed_files": [],
                                            "next_steps": [],
                                        },
                                    },
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    result = smoke_deepseek_provider(
        api_key="secret",
        model="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        transport=transport,
    )

    assert result.provider == "deepseek"
    assert result.model == "deepseek-v4-flash"
    assert result.api_key_env == "DEEPSEEK_API_KEY"
    assert result.status == "ok"
    assert result.action_name == "done"
    assert result.final == "smoke ok"
    assert calls[0][0] == "https://api.deepseek.com/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer secret"
    assert calls[0][2]["model"] == "deepseek-v4-flash"
    assert calls[0][2]["stream"] is False
    assert calls[0][2]["temperature"] == 0
    assert any("done" in message["content"] for message in calls[0][2]["messages"])


def test_deepseek_smoke_accepts_direct_done_action_shape() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "name": "done",
                                    "args": {
                                        "final": "smoke ok",
                                        "changed_files": [],
                                        "next_steps": [],
                                    },
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    result = smoke_deepseek_provider(api_key="secret", transport=transport)

    assert result.action_name == "done"
    assert result.final == "smoke ok"


def test_deepseek_smoke_accepts_direct_done_args_shape() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "final": "smoke ok",
                                    "changed_files": [],
                                    "next_steps": [],
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    result = smoke_deepseek_provider(api_key="secret", transport=transport)

    assert result.action_name == "done"
    assert result.final == "smoke ok"


def test_deepseek_smoke_rejects_missing_api_key_without_network() -> None:
    calls = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        calls.append(url)
        return b"{}"

    with pytest.raises(DeepSeekError) as exc_info:
        smoke_deepseek_provider(api_key="", transport=transport)

    assert "API key is required" in str(exc_info.value)
    assert calls == []


def test_deepseek_smoke_reports_invalid_action_schema() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "Use a tool.",
                                    "action": {"name": "read_file", "args": {"path": "README.md"}},
                                }
                            )
                        }
                    }
                ]
            }
        ).encode("utf-8")

    with pytest.raises(DeepSeekError) as exc_info:
        smoke_deepseek_provider(api_key="secret", transport=transport)

    assert "expected done action" in str(exc_info.value)
