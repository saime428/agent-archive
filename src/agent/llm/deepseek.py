from __future__ import annotations

import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

Transport = Callable[[str, dict[str, str], bytes, float], bytes]


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        timeout: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip():
            raise DeepSeekError("DeepSeek API key is required.")
        if not model.strip():
            raise DeepSeekError("DeepSeek model is required.")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or _urllib_transport

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response_body = self.transport(
                f"{self.base_url}/chat/completions",
                headers,
                body,
                self.timeout,
            )
        except HTTPError as exc:
            raise DeepSeekError(f"DeepSeek API request failed: {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise DeepSeekError(f"DeepSeek API request failed: {exc.reason}") from exc

        return _parse_chat_response(response_body)


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _parse_chat_response(response_body: bytes) -> dict:
    try:
        response = json.loads(response_body.decode("utf-8"))
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepSeekError("DeepSeek API returned an invalid chat completion response.") from exc

    if not isinstance(content, str):
        raise DeepSeekError("DeepSeek API returned non-text model content.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek model content was not a valid JSON action.") from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError("DeepSeek model content must be a valid JSON action object.")
    return parsed
