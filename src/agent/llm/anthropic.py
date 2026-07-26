from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from agent.core.actions import ActionParseError, parse_model_action
from agent.llm.base import ProviderCapabilities
from agent.llm.openai_compat import (
    ProviderError,
    RetrySleep,
    SmokeResult,
    StreamTransport,
    Transport,
    _is_retryable_http,
    _normalize_smoke_action,
    _ReusableHTTPTransport,
    _retry_transient,
)

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# ponytail: the Messages API requires max_tokens; one fixed ceiling is enough
# for the JSON action protocol. Make it configurable only if a real task hits it.
DEFAULT_MAX_TOKENS = 8192


class AnthropicClient:
    capabilities = ProviderCapabilities(streaming=True, native_tools=False)

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_ANTHROPIC_BASE_URL,
        provider_label: str = "Anthropic",
        timeout: float = 60.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        retry_sleep: RetrySleep | None = None,
    ) -> None:
        if not model.strip():
            raise ProviderError(f"{provider_label} model is required.")
        if not base_url.strip():
            raise ProviderError(f"{provider_label} base_url is required.")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_label = provider_label
        self.timeout = timeout
        self.max_tokens = max_tokens
        reusable_transport = _ReusableHTTPTransport()
        self.transport = transport or reusable_transport.request_bytes
        self.stream_transport = stream_transport or reusable_transport.stream_bytes
        self.retry_sleep = retry_sleep or time.sleep

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self.api_key.strip():
            headers["x-api-key"] = self.api_key
        return headers

    def _payload(self, messages: list[dict], *, temperature: float | None, stream: bool) -> bytes:
        system, converted = _convert_messages(messages, self.provider_label)
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        if stream:
            payload["stream"] = True
        return json.dumps(payload, ensure_ascii=True).encode("utf-8")

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict | str:
        body = self._payload(messages, temperature=temperature, stream=False)
        headers = self._headers()
        try:
            response_body = _retry_transient(
                lambda: self.transport(
                    f"{self.base_url}/v1/messages",
                    headers,
                    body,
                    self.timeout,
                ),
                self.retry_sleep,
            )
        except HTTPError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc

        return _parse_messages_response(response_body, self.provider_label)

    def stream_chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> Iterator[str]:
        body = self._payload(messages, temperature=temperature, stream=True)
        headers = self._headers()
        for attempt, delay in enumerate([1.0, 2.0, 4.0, None]):
            try:
                stream = self.stream_transport(
                    f"{self.base_url}/v1/messages",
                    headers,
                    body,
                    self.timeout,
                )
                yield from _parse_streaming_messages_response(stream, self.provider_label)
                return
            except HTTPError as exc:
                if delay is None or not _is_retryable_http(exc):
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
                self.retry_sleep(delay)
            except URLError as exc:
                if delay is None:
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
                self.retry_sleep(delay)


def _convert_messages(messages: list[dict], provider_label: str) -> tuple[str, list[dict]]:
    """Map internal messages onto the Messages API shape.

    System entries merge into the top-level system parameter; the API requires
    strictly alternating user/assistant roles, so consecutive same-role entries
    are joined with a blank line.
    """
    system_parts: list[str] = []
    converted: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError(f"{provider_label} messages must have text content.")
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            raise ProviderError(f"{provider_label} does not support message role: {role!r}.")
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"] = f"{converted[-1]['content']}\n\n{content}"
        else:
            converted.append({"role": role, "content": content})
    if not converted:
        raise ProviderError(f"{provider_label} requires at least one user message.")
    return "\n\n".join(system_parts), converted


def _parse_messages_response(response_body: bytes, provider_label: str) -> dict | str:
    try:
        response = json.loads(response_body.decode("utf-8"))
        blocks = response["content"]
        texts = [block["text"] for block in blocks if block.get("type") == "text"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid messages response.") from exc
    if not all(isinstance(text, str) for text in texts):
        raise ProviderError(f"{provider_label} API returned non-text model content.")
    content = "".join(texts)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider_label} model content must be a valid JSON action object.")
    return parsed


def _parse_streaming_messages_response(chunks: Iterable[bytes], provider_label: str) -> Iterator[str]:
    buffer = ""
    try:
        for chunk in chunks:
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProviderError(f"{provider_label} API returned an invalid streaming response.") from exc
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                result = _parse_stream_event_line(line, provider_label)
                if result is _StreamDone:
                    return
                if result:
                    yield result
        if buffer.strip():
            result = _parse_stream_event_line(buffer, provider_label)
            if result is not _StreamDone and result:
                yield result
    finally:
        close = getattr(chunks, "close", None)
        if callable(close):
            close()


class _StreamDone:
    pass


def _parse_stream_event_line(line: str, provider_label: str) -> str | type[_StreamDone] | None:
    stripped = line.strip()
    # The event type is duplicated inside every data payload, so event:/comment
    # lines carry no extra information here.
    if not stripped or stripped.startswith(":") or stripped.startswith("event:"):
        return None
    if not stripped.startswith("data:"):
        raise ProviderError(f"{provider_label} API returned an invalid streaming response.")
    payload = stripped[len("data:") :].strip()
    try:
        event = json.loads(payload)
        event_type = event.get("type")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid streaming response.") from exc
    if event_type == "message_stop":
        return _StreamDone
    if event_type == "error":
        detail = event.get("error", {})
        raise ProviderError(
            f"{provider_label} API returned a streaming error: {detail.get('message', 'unknown error')}"
        )
    if event_type != "content_block_delta":
        return None
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return None
    text = delta.get("text")
    if not isinstance(text, str):
        raise ProviderError(f"{provider_label} API returned non-text streaming content.")
    return text


def smoke_anthropic_provider(
    *,
    api_key: str,
    model: str,
    base_url: str,
    api_key_env: str,
    provider_label: str = "Anthropic",
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> SmokeResult:
    client = AnthropicClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_label=provider_label,
        timeout=timeout,
        transport=transport,
    )
    raw_action = client.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are testing an agent provider connection. Return only JSON, "
                    "with no markdown, comments, or extra text."
                ),
            },
            {
                "role": "user",
                "content": (
                    'Return exactly this JSON shape: {"message":"Smoke complete.",'
                    '"action":{"name":"done","args":{"final":"smoke ok",'
                    '"changed_files":[],"next_steps":[]}}}'
                ),
            },
        ],
        temperature=0,
    )
    raw_action = _normalize_smoke_action(raw_action)
    try:
        action = parse_model_action(
            raw_action,
            run_id="provider_smoke",
            action_index=1,
            created_at=datetime.now(timezone.utc),
        )
    except ActionParseError as exc:
        raise ProviderError(f"{provider_label} smoke returned invalid action: {exc.message}") from exc
    if action.action.name != "done":
        raise ProviderError(f"{provider_label} smoke expected done action, got {action.action.name}.")

    return SmokeResult(
        provider="anthropic",
        model=model,
        api_key_env=api_key_env,
        status="ok",
        action_name=action.action.name,
        final=action.action.args["final"],
    )
