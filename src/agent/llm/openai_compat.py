from __future__ import annotations

import json
import time
from http.client import HTTPConnection, HTTPSConnection
from collections.abc import Generator, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from agent.core.actions import ActionParseError, parse_model_action


Transport = Callable[[str, dict[str, str], bytes, float], bytes]
StreamTransport = Callable[[str, dict[str, str], bytes, float], Iterable[bytes]]
RetrySleep = Callable[[float], None]


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeResult:
    provider: str
    model: str
    api_key_env: str
    status: str
    action_name: str
    final: str


class OpenAICompatClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider_label: str = "Provider",
        timeout: float = 60.0,
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
        reusable_transport = _ReusableHTTPTransport()
        self.transport = transport or reusable_transport.request_bytes
        self.stream_transport = stream_transport or reusable_transport.stream_bytes
        self.retry_sleep = retry_sleep or time.sleep

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        if self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict | str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = self._headers()

        try:
            response_body = _retry_transient(
                lambda: self.transport(
                    f"{self.base_url}/chat/completions",
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

        return _parse_chat_response(response_body, self.provider_label)

    def stream_chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> Iterator[str]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = self._headers()

        for attempt, delay in enumerate([1.0, 2.0, 4.0, None]):
            try:
                stream = self.stream_transport(
                    f"{self.base_url}/chat/completions",
                    headers,
                    body,
                    self.timeout,
                )
                yield from _parse_streaming_chat_response(stream, self.provider_label)
                return
            except HTTPError as exc:
                if delay is None or not _is_retryable_http(exc):
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
                self.retry_sleep(delay)
            except URLError as exc:
                if delay is None:
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
                self.retry_sleep(delay)

    def chat_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict | str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            response_body = _retry_transient(
                lambda: self.transport(
                    f"{self.base_url}/chat/completions",
                    self._headers(),
                    body,
                    self.timeout,
                ),
                self.retry_sleep,
            )
        except HTTPError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
        return _parse_tools_chat_response(response_body, self.provider_label)

    def stream_chat_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float | None = None,
    ) -> Generator[tuple[str, str], None, dict | str]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        for delay in [1.0, 2.0, 4.0, None]:
            assembler = _ToolCallAssembler()
            try:
                stream = self.stream_transport(
                    f"{self.base_url}/chat/completions",
                    self._headers(),
                    body,
                    self.timeout,
                )
                yield from self._assemble_tool_stream(stream, assembler)
                return assembler.envelope()
            except HTTPError as exc:
                if delay is None or not _is_retryable_http(exc):
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
                self.retry_sleep(delay)
            except URLError as exc:
                if delay is None:
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
                self.retry_sleep(delay)
        raise RuntimeError("unreachable")

    def _assemble_tool_stream(
        self, chunks: Iterable[bytes], assembler: "_ToolCallAssembler"
    ) -> Iterator[tuple[str, str]]:
        buffer = ""
        try:
            for chunk in chunks:
                try:
                    buffer += chunk.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.") from exc
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    pieces = self._tool_stream_piece(line, assembler)
                    if pieces is _StreamDone:
                        return
                    if pieces:
                        yield from pieces
            if buffer.strip():
                pieces = self._tool_stream_piece(buffer, assembler)
                if pieces is not _StreamDone and pieces:
                    yield from pieces
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()

    def _tool_stream_piece(
        self, line: str, assembler: "_ToolCallAssembler"
    ) -> list[tuple[str, str]] | type[_StreamDone] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            return None
        if not stripped.startswith("data:"):
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.")
        payload = stripped[len("data:") :].strip()
        if payload == "[DONE]":
            return _StreamDone
        try:
            event = json.loads(payload)
            delta = event["choices"][0].get("delta") or {}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.") from exc
        if not isinstance(delta, dict):
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.")
        return assembler.feed(delta)


def smoke_provider(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str,
    api_key_env: str,
    provider_label: str = "Provider",
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> SmokeResult:
    client = OpenAICompatClient(
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
            }
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
        provider=provider_name,
        model=model,
        api_key_env=api_key_env,
        status="ok",
        action_name=action.action.name,
        final=action.action.args["final"],
    )


def smoke_provider_native(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str,
    api_key_env: str,
    provider_label: str = "Provider",
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> SmokeResult:
    from agent.core.tool_schemas import build_tool_schemas

    client = OpenAICompatClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_label=provider_label,
        timeout=timeout,
        transport=transport,
    )
    raw_action = client.chat_tools(
        [
            {
                "role": "system",
                "content": "You are testing an agent provider connection. Call the done tool exactly once.",
            },
            {
                "role": "user",
                "content": 'Call the done tool with args {"final":"smoke ok","changed_files":[],"next_steps":[]}.',
            },
        ],
        build_tool_schemas(["done"]),
        temperature=0,
    )
    try:
        action = parse_model_action(
            raw_action,
            run_id="provider_smoke",
            action_index=1,
            created_at=datetime.now(timezone.utc),
        )
    except ActionParseError as exc:
        raise ProviderError(f"{provider_label} native smoke returned invalid action: {exc.message}") from exc
    if action.action.name != "done":
        raise ProviderError(f"{provider_label} native smoke expected done action, got {action.action.name}.")
    return SmokeResult(
        provider=provider_name,
        model=model,
        api_key_env=api_key_env,
        status="ok",
        action_name=action.action.name,
        final=str(action.action.args["final"]),
    )


def _normalize_smoke_action(raw_action: dict | str) -> dict | str:
    if not isinstance(raw_action, dict):
        return raw_action
    if _looks_like_action_envelope(raw_action):
        return raw_action
    if raw_action.get("action") and "message" not in raw_action:
        return {"message": "Smoke complete.", "action": raw_action["action"]}
    if raw_action.get("name") == "done" and isinstance(raw_action.get("args"), dict):
        return {"message": "Smoke complete.", "action": raw_action}
    if {"final", "changed_files", "next_steps"} <= raw_action.keys():
        return {
            "message": "Smoke complete.",
            "action": {
                "name": "done",
                "args": {
                    "final": raw_action["final"],
                    "changed_files": raw_action["changed_files"],
                    "next_steps": raw_action["next_steps"],
                },
            },
        }
    return raw_action


def _looks_like_action_envelope(raw_action: dict) -> bool:
    return isinstance(raw_action.get("message"), str) and isinstance(raw_action.get("action"), dict)


def _retry_transient(call: Callable[[], bytes], sleep: RetrySleep) -> bytes:
    for delay in [1.0, 2.0, 4.0, None]:
        try:
            return call()
        except HTTPError as exc:
            if delay is None or not _is_retryable_http(exc):
                raise
            sleep(delay)
        except URLError:
            if delay is None:
                raise
            sleep(delay)
    raise RuntimeError("unreachable")


def _is_retryable_http(exc: HTTPError) -> bool:
    return exc.code == 429 or 500 <= exc.code <= 599


class _ReusableHTTPTransport:
    def __init__(self) -> None:
        self._connections: dict[tuple[str, str, int | None], HTTPConnection] = {}

    def request_bytes(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        response = self._request(url, headers, body, timeout)
        data = response.read()
        self._drop_closed_connection(url, response.will_close)
        return data

    def stream_bytes(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> Iterable[bytes]:
        response = self._request(url, headers, body, timeout)
        completed = False
        try:
            yield from response
            completed = True
        finally:
            if not completed or response.will_close:
                # An abandoned stream leaves unread data on the keep-alive
                # connection; it must not be reused for the next request.
                try:
                    response.close()
                finally:
                    self._drop_connection(url)

    def _request(self, url: str, headers: dict[str, str], body: bytes, timeout: float):
        parsed = urlparse(url)
        connection = self._connection(parsed.scheme, parsed.hostname or "", parsed.port, timeout)
        target = parsed.path or "/"
        if parsed.query:
            target += f"?{parsed.query}"
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        if response.status >= 400:
            raise HTTPError(url, response.status, response.reason, hdrs=response.headers, fp=None)
        return response

    def _connection(self, scheme: str, host: str, port: int | None, timeout: float) -> HTTPConnection:
        key = (scheme, host, port)
        connection = self._connections.get(key)
        if connection is None:
            cls = HTTPSConnection if scheme == "https" else HTTPConnection
            connection = cls(host, port=port, timeout=timeout)
            self._connections[key] = connection
        return connection

    def _drop_closed_connection(self, url: str, will_close: bool) -> None:
        if not will_close:
            return
        self._drop_connection(url)

    def _drop_connection(self, url: str) -> None:
        parsed = urlparse(url)
        key = (parsed.scheme, parsed.hostname or "", parsed.port)
        connection = self._connections.pop(key, None)
        if connection is not None:
            connection.close()


def _parse_chat_response(response_body: bytes, provider_label: str) -> dict | str:
    try:
        response = json.loads(response_body.decode("utf-8"))
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid chat completion response.") from exc

    if not isinstance(content, str):
        raise ProviderError(f"{provider_label} API returned non-text model content.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider_label} model content must be a valid JSON action object.")
    return parsed


def _parse_tools_chat_response(response_body: bytes, provider_label: str) -> dict | str:
    try:
        response = json.loads(response_body.decode("utf-8"))
        message_obj = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid chat completion response.") from exc
    if not isinstance(message_obj, dict):
        raise ProviderError(f"{provider_label} API returned an invalid chat completion response.")
    return _envelope_from_tool_message(message_obj)


def _envelope_from_tool_message(message_obj: dict) -> dict | str:
    content = message_obj.get("content")
    message_text = content if isinstance(content, str) else ""
    tool_calls = message_obj.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return {"message": message_text}
    first = tool_calls[0]
    function = first.get("function") if isinstance(first, dict) else None
    if not isinstance(function, dict):
        return {"message": message_text}
    name = function.get("name")
    arguments = function.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, str):
        return {"message": message_text}
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if not isinstance(args, dict):
        return arguments
    return {"message": message_text, "action": {"name": name, "args": args}}


class _ToolCallAssembler:
    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.tool_name: str | None = None
        self.argument_parts: list[str] = []

    def feed(self, delta: dict) -> list[tuple[str, str]]:
        pieces: list[tuple[str, str]] = []
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            pieces.append(("thinking", reasoning))
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.content_parts.append(content)
            pieces.append(("content", content))
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for fragment in tool_calls:
                if not isinstance(fragment, dict) or fragment.get("index", 0) != 0:
                    continue
                function = fragment.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if isinstance(name, str) and name and self.tool_name is None:
                    self.tool_name = name
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments:
                    self.argument_parts.append(arguments)
                    pieces.append(("args", arguments))
        return pieces

    def envelope(self) -> dict | str:
        message_obj: dict[str, object] = {"content": "".join(self.content_parts)}
        if self.tool_name is not None:
            message_obj["tool_calls"] = [
                {"function": {"name": self.tool_name, "arguments": "".join(self.argument_parts)}}
            ]
        return _envelope_from_tool_message(message_obj)


def _parse_streaming_chat_response(chunks: Iterable[bytes], provider_label: str) -> Iterator[str]:
    buffer = ""
    try:
        for chunk in chunks:
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProviderError(f"{provider_label} API returned an invalid streaming response.") from exc
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                result = _parse_sse_line(line, provider_label)
                if result is _StreamDone:
                    return
                if result:
                    yield result
        if buffer.strip():
            result = _parse_sse_line(buffer, provider_label)
            if result is not _StreamDone and result:
                yield result
    finally:
        close = getattr(chunks, "close", None)
        if callable(close):
            close()


class _StreamDone:
    pass


def _parse_sse_line(line: str, provider_label: str) -> str | type[_StreamDone] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if not stripped.startswith("data:"):
        raise ProviderError(f"{provider_label} API returned an invalid streaming response.")
    payload = stripped[len("data:") :].strip()
    if payload == "[DONE]":
        return _StreamDone
    try:
        event = json.loads(payload)
        content = event["choices"][0]["delta"].get("content")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid streaming response.") from exc
    if content is None:
        return None
    if not isinstance(content, str):
        raise ProviderError(f"{provider_label} API returned non-text streaming content.")
    return content
