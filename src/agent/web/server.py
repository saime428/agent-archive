from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent.config import ConfigError
from agent.core.run_store import RunStoreError
from agent.llm.deepseek import DeepSeekError
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


def static_file_path(relative_path: str) -> Path:
    candidate = (STATIC_ROOT / relative_path).resolve()
    root = STATIC_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Static path resolves outside the workbench assets.")
    return candidate


def serve_workbench(*, workspace: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    handler = create_workbench_handler(workspace.resolve())
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"Agent Workbench: {url}", flush=True)
    print(f"workspace: {workspace.resolve()}", flush=True)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgent Workbench stopped.")
    finally:
        server.server_close()


def create_workbench_handler(workspace: Path) -> type[BaseHTTPRequestHandler]:
    root = workspace.resolve()
    runtime = ChatRuntime(root)

    class WorkbenchHandler(BaseHTTPRequestHandler):
        server_version = "AgentWorkbench/0.1"

        def do_GET(self) -> None:  # noqa: N802
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
                    self._send_sse(_query_value(parsed.query, "job_id"))
                    return
                if path == "/api/files":
                    self._send_json(build_files_payload(root, _query_value(parsed.query, "path")))
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
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/api/chat/turn":
                    self._send_json(_build_chat_turn_payload(root, self._read_json_body()))
                    return
                if path == "/api/chat/start":
                    request = self._read_json_body()
                    message = request.get("message")
                    if not isinstance(message, str) or not message.strip():
                        raise ValueError("message is required.")
                    session_id = request.get("session_id")
                    if session_id is not None and not isinstance(session_id, str):
                        raise ValueError("session_id must be a string.")
                    self._send_json(runtime.start(message=message.strip(), session_id=session_id))
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
                    self._send_json(_build_chat_rename_payload(root, self._read_json_body()))
                    return
                if path == "/api/chat/delete":
                    self._send_json(_build_chat_delete_payload(root, self._read_json_body()))
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
                self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"Invalid JSON body: {exc.msg}"}, status=HTTPStatus.BAD_REQUEST)
            except (ConfigError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except DeepSeekError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            except OSError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("JSON body is required.")
            if length > 64_000:
                raise ValueError("JSON body is too large.")
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object.")
            return payload

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path: str) -> None:
            relative_path = "index.html" if path in {"", "/"} else path.lstrip("/")
            file_path = static_file_path(relative_path)
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            body = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_sse(self, job_id: str | None) -> None:
            if not job_id:
                self._send_json({"error": "job_id is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = runtime.poll(job_id, after=0, timeout=0)
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

    return WorkbenchHandler


def _query_value(query: str, key: str) -> str | None:
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        if unquote(name) == key:
            return unquote(value)
    return None
