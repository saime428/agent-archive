from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from agent.llm.deepseek import DeepSeekClient, DeepSeekError


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
