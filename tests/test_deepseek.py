from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

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


def test_deepseek_client_reports_invalid_model_content() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode("utf-8")

    client = DeepSeekClient(api_key="secret", transport=transport)

    with pytest.raises(DeepSeekError) as exc_info:
        client.chat([{"role": "user", "content": "finish"}])

    assert "valid JSON action" in str(exc_info.value)


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
    assert "done" in calls[0][2]["messages"][0]["content"]


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
