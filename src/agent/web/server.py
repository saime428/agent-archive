from __future__ import annotations

import json
import mimetypes
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent.config import ConfigError, load_config
from agent.core.budget import ContextBudget, truncate_text
from agent.core.chat import ChatSession, ConversationState
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DeepSeekError
from agent.llm.factory import make_llm
from agent.policy.sandbox import SandboxError, WorkspaceSandbox


STATIC_ROOT = Path(__file__).resolve().parent / "static"


def static_file_path(relative_path: str) -> Path:
    candidate = (STATIC_ROOT / relative_path).resolve()
    root = STATIC_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Static path resolves outside the workbench assets.")
    return candidate


def serve_workbench(*, workspace: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = create_workbench_handler(workspace.resolve())
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"Agent Workbench: {url}")
    print(f"workspace: {workspace.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgent Workbench stopped.")
    finally:
        server.server_close()


def create_workbench_handler(workspace: Path) -> type[BaseHTTPRequestHandler]:
    root = workspace.resolve()

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
                if path == "/api/tools":
                    self._send_json(build_tools_payload())
                    return
                if path == "/api/runs":
                    self._send_json(build_runs_payload(root))
                    return
                if path == "/api/files":
                    self._send_json(build_files_payload(root, _query_value(parsed.query, "path")))
                    return
                if path == "/api/file":
                    self._send_json(build_file_payload(root, _query_value(parsed.query, "path")))
                    return
                if path.startswith("/api/runs/"):
                    run_id = path.rsplit("/", 1)[-1]
                    self._send_json(build_run_detail_payload(root, run_id))
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
                    self._send_json(build_chat_turn_payload(root, self._read_json_body()))
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

    return WorkbenchHandler


def build_health_payload(workspace: Path) -> dict[str, Any]:
    config_payload = build_config_payload(workspace)
    config = config_payload["config"]
    return {
        "status": "ok",
        "app": "agent-workbench",
        "workspace": str(workspace.resolve()),
        "provider": config["provider"],
        "model": config["model"],
        "mode": config["mode"],
    }


def build_config_payload(workspace: Path) -> dict[str, Any]:
    config, diagnostics = load_config(workspace.resolve())
    config_record = asdict(config)
    for key in ("default_skills", "enabled_hooks", "blocking_hooks"):
        config_record[key] = list(config_record[key])
    return {
        "workspace": str(workspace.resolve()),
        "config": config_record,
        "diagnostics": {
            "global_config_path": str(diagnostics.global_config_path),
            "project_config_path": str(diagnostics.project_config_path),
            "loaded_files": [str(path.resolve()) for path in diagnostics.loaded_files],
            "warnings": diagnostics.warnings,
        },
    }


def build_tools_payload() -> dict[str, Any]:
    return {"tools": [asdict(tool) for tool in list_tool_infos()]}


def build_runs_payload(workspace: Path, *, limit: int = 20) -> dict[str, Any]:
    runs = RunStore(workspace.resolve()).list_runs(limit=limit)
    return {
        "workspace": str(workspace.resolve()),
        "runs": [
            {
                "run_id": run.run_id,
                "run_dir": str(run.run_dir),
                "summary_path": str(run.summary_path),
                "tool_calls_path": str(run.tool_calls_path),
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
            }
            for run in runs
        ],
    }


def build_files_payload(workspace: Path, path: str | None = None) -> dict[str, Any]:
    root = workspace.resolve()
    sandbox = WorkspaceSandbox(root)
    requested = path or "."
    try:
        directory = sandbox.resolve_read_path(requested)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not directory.exists():
        raise ValueError(f"Directory not found: {requested}")
    if not directory.is_dir():
        raise ValueError(f"Path is not a directory: {requested}")
    entries = []
    for entry in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": entry.name,
                "path": _display_path(entry, root),
                "kind": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            }
        )
    return {"path": _display_path(directory, root), "entries": entries}


def build_file_payload(workspace: Path, path: str | None, *, max_chars: int | None = None) -> dict[str, Any]:
    if not path:
        raise ValueError("path is required.")
    root = workspace.resolve()
    sandbox = WorkspaceSandbox(root)
    try:
        file_path = sandbox.resolve_read_path(path)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    budget = ContextBudget()
    limit = min(max_chars or budget.file_read_max_chars, budget.file_read_max_chars)
    with file_path.open("rb") as handle:
        sample = handle.read(min(limit, 4096))
    if b"\x00" in sample:
        raise ValueError(f"Binary file preview is not supported: {path}")
    content = file_path.read_text(encoding="utf-8", errors="replace")
    truncated = truncate_text(content, limit)
    return {
        "path": _display_path(file_path, root),
        "content": truncated.value,
        "truncated": truncated.truncated,
        "size": file_path.stat().st_size,
    }


def build_chat_turn_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    message = request.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message is required.")
    session_id = request.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise ValueError("session_id must be a string.")
    approve_once = request.get("approve_once", False)
    if not isinstance(approve_once, bool):
        raise ValueError("approve_once must be a boolean.")

    root = workspace.resolve()
    config, diagnostics = load_config(root)
    state = ConversationState.load(root, session_id) if session_id else ConversationState.create(root)
    session = ChatSession(cwd=root, llm=make_llm(config), config=config, state=state)
    result = session.run_turn(message.strip(), approval_handler=_approve_once_handler() if approve_once else None)
    turn = session.state.turns[-1]
    error = result.observation.error
    error_code = str(error.code) if error is not None else None
    return {
        "session_id": session.state.session_id,
        "turn_count": len(session.state.turns),
        "run_id": turn.run_id,
        "status": turn.status,
        "completed": turn.completed,
        "terminal_reason": turn.terminal_reason,
        "final": turn.final,
        "last_action": turn.last_action,
        "last_observation_summary": turn.last_observation_summary,
        "summary_path": str(result.summary_path),
        "error_code": error_code,
        "error_message": error.message if error is not None else None,
        "approval_required": error_code == "APPROVAL_REQUIRED",
        "requested_action": result.action.action.name,
        "config_warnings": diagnostics.warnings,
    }


def _approve_once_handler():
    approved = False

    def approve_once(_action: Any) -> bool:
        nonlocal approved
        if approved:
            return False
        approved = True
        return True

    return approve_once


def build_run_detail_payload(workspace: Path, run_id: str) -> dict[str, Any]:
    detail = RunStore(workspace.resolve()).show_run(run_id)
    return {
        "run_id": detail.run_id,
        "run_dir": str(detail.run_dir),
        "summary": detail.summary,
        "tool_calls": [
            {
                "line_number": call.line_number,
                "valid": call.valid,
                "raw": call.raw,
                "data": call.data,
                "error": call.error,
            }
            for call in detail.tool_calls
        ],
        "snapshots": detail.snapshots,
    }


def _query_value(query: str, key: str) -> str | None:
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        if unquote(name) == key:
            return unquote(value)
    return None


def _display_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    value = relative.as_posix()
    return value or "."
