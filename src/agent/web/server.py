from __future__ import annotations

import gzip
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent.config import ConfigError
from agent.core.run_control import validate_timeout_seconds
from agent.core.run_store import RunStoreError
from agent.llm.deepseek import DeepSeekError
from agent.mcp_runtime import McpRuntimeError, McpStdioRuntime
from agent.policy.sandbox import SandboxError
from agent.web.chats import (
    build_chat_delete_payload as _build_chat_delete_payload,
    build_chat_payload as _build_chat_payload,
    build_chat_rename_payload as _build_chat_rename_payload,
    build_chat_turn_payload as _build_chat_turn_payload,
    build_chats_payload as _build_chats_payload,
)
from agent.web.chat_runtime import ChatRuntime
from agent.web.files import (
    build_diff_payload,
    build_file_payload,
    build_files_payload,
    build_restore_snapshot_payload,
    build_save_file_payload,
    build_search_payload,
)
from agent.web.runs import (
    build_run_detail_payload as _build_run_detail_payload,
    build_runs_payload as _build_runs_payload,
)
from agent.web.settings import (
    build_config_payload,
    build_health_payload,
    build_save_config_payload,
    build_tools_payload,
)


STATIC_ROOT = Path(__file__).resolve().parent / "static"

# The React Workbench is the default; "/legacy/" remains the one-line rollback entry.
_STATIC_ENTRYPOINTS = {
    "/": "preview/index.html",
    "/preview/": "preview/index.html",
    "/legacy/": "index.html",
}
_MAX_JSON_BODY_BYTES = 64_000
_ENTRYPOINT_ALIASES = {"/preview": "/preview/", "/legacy": "/legacy/"}


def static_file_path(relative_path: str) -> Path:
    candidate = (STATIC_ROOT / relative_path).resolve()
    root = STATIC_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Static path resolves outside the workbench assets.")
    return candidate


def serve_workbench(*, workspace: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    if not _is_loopback_host(host):
        raise ValueError("Agent Workbench host must be a loopback address.")
    root = workspace.resolve()
    mcp_runtime = McpStdioRuntime(root)
    server: ThreadingHTTPServer | None = None
    try:
        handler = create_workbench_handler(root, mcp_runtime=mcp_runtime)
        server = ThreadingHTTPServer((host, port), handler)
        server.daemon_threads = True
        url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        url = f"http://{url_host}:{port}"
        print(f"Agent Workbench: {url}", flush=True)
        print(f"workspace: {root}", flush=True)
        if open_browser:
            threading.Timer(0.2, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nAgent Workbench stopped.")
    finally:
        try:
            if server is not None:
                server.server_close()
        finally:
            mcp_runtime.close()


def create_workbench_handler(
    workspace: Path,
    *,
    mcp_runtime: Any | None = None,
) -> type[BaseHTTPRequestHandler]:
    root = workspace.resolve()
    runtime = (
        ChatRuntime(root)
        if mcp_runtime is None
        else ChatRuntime(root, mcp_runtime=mcp_runtime)
    )

    class WorkbenchHandler(BaseHTTPRequestHandler):
        server_version = "AgentWorkbench/0.1"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorize_request(state_change=False):
                return
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/api/health":
                    self._send_json(build_health_payload(root))
                    return
                if path == "/api/config":
                    self._send_json(build_config_payload(root))
                    return
                if path == "/api/chats":
                    self._send_json(_build_chats_payload(root))
                    return
                if path == "/api/tools":
                    self._send_json(build_tools_payload())
                    return
                if path == "/api/runs":
                    self._send_json(_build_runs_payload(root))
                    return
                if path == "/api/chat/events":
                    self._send_sse(
                        _query_value(parsed.query, "job_id"),
                        _parse_after(_query_value(parsed.query, "after")),
                    )
                    return
                if path == "/api/files":
                    self._send_json(build_files_payload(root, _query_value(parsed.query, "path")))
                    return
                if path == "/api/search":
                    self._send_json(build_search_payload(root, _query_value(parsed.query, "query")))
                    return
                if path == "/api/file":
                    self._send_json(build_file_payload(root, _query_value(parsed.query, "path")))
                    return
                if path == "/api/diff":
                    self._send_json(
                        build_diff_payload(
                            root,
                            _query_value(parsed.query, "path"),
                            _query_value(parsed.query, "snapshot"),
                        )
                    )
                    return
                if path.startswith("/api/chats/"):
                    session_id = path.rsplit("/", 1)[-1]
                    self._send_json(_build_chat_payload(root, session_id))
                    return
                if path.startswith("/api/runs/"):
                    run_id = path.rsplit("/", 1)[-1]
                    self._send_json(_build_run_detail_payload(root, run_id))
                    return
                alias_target = _ENTRYPOINT_ALIASES.get(path)
                if alias_target is not None:
                    self._send_entrypoint_redirect(alias_target, parsed.query)
                    return
                self._send_static(path)
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except RunStoreError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except (ValueError, SandboxError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except OSError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorize_request(state_change=True):
                return
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/api/chat/turn":
                    request = self._read_json_body()
                    with runtime._reserve_turn(request.get("session_id")):
                        self._send_json(
                            _build_chat_turn_payload(root, request)
                            if mcp_runtime is None
                            else _build_chat_turn_payload(
                                root, request, mcp_runtime=mcp_runtime
                            )
                        )
                    return
                if path == "/api/chat/start":
                    request = self._read_json_body()
                    message = request.get("message")
                    if not isinstance(message, str) or not message.strip():
                        raise ValueError("message is required.")
                    session_id = request.get("session_id")
                    if session_id is not None and not isinstance(session_id, str):
                        raise ValueError("session_id must be a string.")
                    timeout_seconds = validate_timeout_seconds(request.get("timeout_seconds"))
                    self._send_json(
                        runtime.start(
                            message=message.strip(),
                            session_id=session_id,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    return
                if path == "/api/chat/cancel":
                    request = self._read_json_body()
                    job_id = request.get("job_id")
                    if not isinstance(job_id, str) or not job_id:
                        raise ValueError("job_id is required.")
                    self._send_json(runtime.cancel(job_id))
                    return
                if path == "/api/chat/resume":
                    request = self._read_json_body()
                    job_id = request.get("job_id")
                    if not isinstance(job_id, str) or not job_id:
                        raise ValueError("job_id is required.")
                    message = request.get("message")
                    if not isinstance(message, str) or not message.strip():
                        raise ValueError("message is required.")
                    timeout_seconds = validate_timeout_seconds(request.get("timeout_seconds"))
                    self._send_json(
                        runtime.resume(
                            job_id=job_id,
                            message=message.strip(),
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    return
                if path == "/api/chat/approval":
                    request = self._read_json_body()
                    job_id = request.get("job_id")
                    approve = request.get("approve")
                    if not isinstance(job_id, str) or not job_id:
                        raise ValueError("job_id is required.")
                    if not isinstance(approve, bool):
                        raise ValueError("approve must be a boolean.")
                    self._send_json(runtime.decide(job_id=job_id, approve=approve))
                    return
                if path == "/api/chat/rename":
                    request = self._read_json_body()
                    with runtime._reserve_session(request.get("session_id")):
                        self._send_json(_build_chat_rename_payload(root, request))
                    return
                if path == "/api/chat/delete":
                    request = self._read_json_body()
                    with runtime._reserve_session(request.get("session_id")):
                        self._send_json(_build_chat_delete_payload(root, request))
                    return
                if path == "/api/config":
                    self._send_json(build_save_config_payload(root, self._read_json_body()))
                    return
                if path == "/api/snapshot/restore":
                    self._send_json(build_restore_snapshot_payload(root, self._read_json_body()))
                    return
                if path == "/api/file/save":
                    self._send_json(build_save_file_payload(root, self._read_json_body()))
                    return
                self._discard_bounded_request_body()
                self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"Invalid JSON body: {exc.msg}"}, status=HTTPStatus.BAD_REQUEST)
            except (ConfigError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except DeepSeekError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            except McpRuntimeError as exc:
                status = HTTPStatus.BAD_REQUEST if exc.stage == "config" else HTTPStatus.BAD_GATEWAY
                self._send_json({"error": str(exc)}, status=status)
            except OSError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

        def end_headers(self) -> None:
            self._send_security_headers()
            super().end_headers()

        def _authorize_request(self, *, state_change: bool) -> bool:
            host = self.headers.get("Host")
            host_parts = _host_header_parts(host)
            if host_parts is None or not _is_loopback_host(host_parts[0]):
                self._discard_bounded_request_body()
                self._send_json(
                    {"error": "Workbench only accepts loopback requests."},
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            if not state_change:
                return True
            fetch_site = self.headers.get("Sec-Fetch-Site", "").casefold()
            origin = self.headers.get("Origin")
            if fetch_site == "cross-site" or (origin is not None and not _origin_matches_host(origin, host_parts, self.server.server_port)):
                self._discard_bounded_request_body()
                self._send_json(
                    {"error": "Cross-origin Workbench writes are not allowed."},
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            return True

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("JSON body is required.")
            if length > _MAX_JSON_BODY_BYTES:
                raise ValueError("JSON body is too large.")
            raw = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "").partition(";")[0].strip().casefold()
            if content_type != "application/json":
                raise ValueError("Content-Type must be application/json.")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object.")
            return payload

        def _discard_bounded_request_body(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return
            if 0 < length <= _MAX_JSON_BODY_BYTES:
                self.rfile.read(length)

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_entrypoint_redirect(self, target: str, query: str) -> None:
            location = f"{target}?{query}" if query else target
            self.send_response(HTTPStatus.PERMANENT_REDIRECT)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_static(self, path: str) -> None:
            entrypoint = _STATIC_ENTRYPOINTS.get(path)
            if entrypoint is not None:
                relative_path = entrypoint
            else:
                relative_path = path.lstrip("/")
                if not relative_path or path.endswith("/"):
                    relative_path = f"{relative_path}index.html"
            file_path = static_file_path(relative_path)
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            body = file_path.read_bytes()
            compressible = content_type.startswith("text/") or content_type in {
                "application/javascript",
                "application/json",
            }
            use_gzip = (
                compressible
                and len(body) >= 1024
                and _accepts_gzip(self.headers.get("Accept-Encoding"))
            )
            if use_gzip:
                body = gzip.compress(body, compresslevel=6, mtime=0)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            if compressible:
                self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            if content_type == "text/html":
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_sse(self, job_id: str | None, after: int) -> None:
            if not job_id:
                self._send_json({"error": "job_id is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = runtime.poll(job_id, after=after, timeout=0)
            try:
                self.close_connection = True
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    events = payload["events"]
                    for event in events:
                        data = json.dumps(event, ensure_ascii=False, default=str)
                        chunk = f"id: {event['sequence']}\nevent: {event['event']}\ndata: {data}\n\n"
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                    if payload["done"]:
                        return
                    try:
                        payload = runtime.poll(job_id, after=payload["next"], timeout=10.0)
                    except ValueError:
                        return
            except OSError:
                return

        def _send_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; connect-src 'self'; "
                "script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )

    return WorkbenchHandler


def _accepts_gzip(value: str | None) -> bool:
    wildcard_quality: float | None = None
    for item in (value or "").casefold().split(","):
        coding, *parameters = item.split(";")
        if coding.strip() not in {"gzip", "*"}:
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, raw_value = parameter.partition("=")
            if separator and name.strip() == "q":
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
        if coding.strip() == "gzip":
            return quality > 0
        wildcard_quality = quality
    return wildcard_quality is not None and wildcard_quality > 0


def _query_value(query: str, key: str) -> str | None:
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        if unquote(name) == key:
            return unquote(value)
    return None


def _parse_after(value: str | None) -> int:
    if value is None:
        return 0
    if not value or not value.isascii() or not value.isdigit():
        raise ValueError("after must be a non-negative integer.")
    return int(value)


def _is_loopback_host(host: str) -> bool:
    candidate = host.strip().strip("[]")
    if candidate.casefold() == "localhost":
        return True
    try:
        return ip_address(candidate).is_loopback
    except ValueError:
        return False


def _host_header_parts(value: str | None) -> tuple[str, int | None] | None:
    if not value or "@" in value:
        return None
    try:
        parsed = urlparse(f"//{value}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not hostname:
        return None
    return hostname, port


def _origin_matches_host(origin: str, host: tuple[str, int | None], server_port: int) -> bool:
    try:
        parsed = urlparse(origin)
        origin_port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "http" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        return False
    host_name, host_port = host
    return parsed.hostname.casefold() == host_name.casefold() and (origin_port or 80) == (host_port or server_port)
