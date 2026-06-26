from __future__ import annotations

import difflib
import json
import mimetypes
import os
import shutil
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent.config import ConfigError, load_config
from agent.core.actions import ActionCall, InternalAction, make_observation
from agent.core.budget import ContextBudget, truncate_text
from agent.core.chat import ChatSession, ConversationState
from agent.core.context import RunContext
from agent.core.redaction import redact_record, redact_value
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DeepSeekError
from agent.llm.factory import make_llm
from agent.policy.sandbox import SandboxError, WorkspaceSandbox
from agent.tools.filesystem import create_snapshot


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
                if path == "/api/diff":
                    self._send_json(
                        build_diff_payload(
                            root,
                            _query_value(parsed.query, "path"),
                            _query_value(parsed.query, "snapshot"),
                        )
                    )
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


def build_save_file_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    path = request.get("path")
    content = request.get("content")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required.")
    if not isinstance(content, str):
        raise ValueError("content is required.")

    root = workspace.resolve()
    try:
        file_path = WorkspaceSandbox(root).resolve_write_path(path, create_parents=False)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    with file_path.open("rb") as handle:
        if b"\x00" in handle.read(4096):
            raise ValueError(f"Binary file editing is not supported: {path}")

    context = RunContext.create("Workbench file editor save", cwd=root)
    action = InternalAction(
        run_id=context.run_id,
        action_id="act_000001",
        created_at=context.created_at,
        message="Workbench file editor save.",
        action=ActionCall(
            name="write_file",
            args={
                "path": _display_path(file_path, root),
                "source": "workbench-file-editor",
                "bytes": len(content.encode("utf-8")),
            },
        ),
    )
    snapshot = create_snapshot(file_path, context, action_id=action.action_id)
    encoded = content.encode("utf-8")
    file_path.write_bytes(encoded)
    observation = make_observation(
        action,
        observation_index=1,
        summary=f"Saved {len(encoded)} bytes from Workbench file editor.",
        data={
            "path": _display_path(file_path, root),
            "bytes_written": len(encoded),
            "snapshot_path": _display_path(snapshot.snapshot_path, root),
            "previously_existed": snapshot.previously_existed,
            "restore_hint": snapshot.restore_hint,
        },
    )
    _write_workbench_file_save_log(context, action, observation)
    return {
        "status": "ok",
        "run_id": context.run_id,
        "path": _display_path(file_path, root),
        "bytes_written": len(encoded),
        "snapshot_path": _display_path(snapshot.snapshot_path, root),
        "restore_hint": snapshot.restore_hint,
    }


def build_diff_payload(
    workspace: Path,
    path: str | None,
    snapshot: str | None,
    *,
    max_chars: int | None = None,
) -> dict[str, Any]:
    if not path:
        raise ValueError("path is required.")
    if not snapshot:
        raise ValueError("snapshot is required.")
    root = workspace.resolve()
    sandbox = WorkspaceSandbox(root)
    try:
        current_path = sandbox.resolve_read_path(path)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    snapshot_path = _resolve_snapshot_path(root, snapshot)

    old_text, snapshot_missing = _snapshot_text(snapshot_path, snapshot)
    new_text = "" if not current_path.exists() else _read_text_for_diff(current_path, path)
    display_path = _display_path(current_path, root)
    diff = "\n".join(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"snapshot/{display_path}",
            tofile=f"current/{display_path}",
            lineterm="",
        )
    )
    budget = ContextBudget()
    limit = min(max_chars or budget.file_read_max_chars, budget.file_read_max_chars)
    truncated = truncate_text(diff, limit)
    return {
        "path": display_path,
        "snapshot_path": _display_path(snapshot_path, root),
        "diff": truncated.value,
        "truncated": truncated.truncated,
        "current_exists": current_path.exists(),
        "snapshot_missing": snapshot_missing,
    }


def build_restore_snapshot_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    path = request.get("path")
    snapshot = request.get("snapshot_path")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required.")
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("snapshot_path is required.")

    root = workspace.resolve()
    snapshot_path = _resolve_snapshot_path(root, snapshot)
    metadata = _snapshot_metadata(snapshot_path)
    target_path = _restore_target_path(root, str(metadata.get("path") or path))
    previously_existed = metadata.get("previously_existed")
    if not isinstance(previously_existed, bool):
        raise ValueError("Snapshot metadata is missing previously_existed.")

    if previously_existed:
        original = _resolve_snapshot_path(root, str(metadata.get("snapshot_file") or snapshot))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target_path)
        action = "restored"
    else:
        if target_path.exists():
            if not target_path.is_file():
                raise ValueError(f"Restore target is not a file: {path}")
            target_path.unlink()
        action = "deleted"

    return {
        "status": "ok",
        "action": action,
        "path": _display_path(target_path, root),
        "snapshot_path": _display_path(snapshot_path, root),
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


def _resolve_snapshot_path(root: Path, snapshot: str) -> Path:
    requested = Path(snapshot)
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve()
    runs_root = (root / ".agent" / "runs").resolve()
    if not _is_within(resolved, runs_root):
        raise ValueError("SANDBOX_VIOLATION: Snapshot path must stay under .agent/runs.")
    relative_parts = resolved.relative_to(runs_root).parts
    if len(relative_parts) < 3 or relative_parts[1] != "snapshots":
        raise ValueError("SANDBOX_VIOLATION: Snapshot path must stay under .agent/runs snapshots.")
    if not resolved.exists():
        raise ValueError(f"Snapshot not found: {snapshot}")
    if not resolved.is_file():
        raise ValueError(f"Snapshot path is not a file: {snapshot}")
    return resolved


def _snapshot_text(path: Path, requested: str) -> tuple[str, bool]:
    if path.name == "metadata.json":
        metadata = _read_json_file(path)
        if isinstance(metadata, dict) and metadata.get("previously_existed") is False:
            return "", True
    return _read_text_for_diff(path, requested), False


def _snapshot_metadata(snapshot_path: Path) -> dict[str, Any]:
    metadata_path = snapshot_path if snapshot_path.name == "metadata.json" else snapshot_path.parent / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError(f"Snapshot metadata missing: {metadata_path}")
    metadata = _read_json_file(metadata_path)
    if not isinstance(metadata, dict):
        raise ValueError(f"Snapshot metadata must be an object: {metadata_path}")
    return metadata


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid snapshot metadata: {path}") from exc


def _restore_target_path(root: Path, path: str) -> Path:
    try:
        return WorkspaceSandbox(root).resolve_write_path(path, create_parents=True)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc


def _read_text_for_diff(path: Path, label: str) -> str:
    if path.is_dir():
        raise ValueError(f"Diff path is not a file: {label}")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError(f"Binary diff is not supported: {label}")
    return raw.decode("utf-8", errors="replace")


def _write_workbench_file_save_log(context: RunContext, action: InternalAction, observation: Any) -> None:
    run_dir = context.cwd / ".agent" / "runs" / context.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "action": action.model_dump(mode="json"),
        "observation": observation.model_dump(mode="json"),
        "trace": {
            "phase": "workbench",
            "action_index": 1,
            "observation_index": 1,
            "repair_attempt": 0,
            "terminal": True,
        },
    }
    redacted_record = redact_record(record)
    serialized_record = redacted_record.value
    if redacted_record.applied:
        serialized_record["redaction"] = {
            "applied": True,
            "replacements": redacted_record.replacements,
        }
    (run_dir / "tool_calls.jsonl").write_text(
        json.dumps(serialized_record, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    data = observation.data or {}
    summary = "\n".join(
        [
            f"# Run {context.run_id}",
            "",
            "- task: Workbench file editor save",
            "- action: write_file",
            f"- status: {observation.status}",
            "- completed: true",
            "- terminal_reason: workbench_file_save",
            "- final: Saved file from Workbench file editor.",
            f"- last_action: {action.action.name}",
            f"- last_observation_summary: {observation.summary}",
            "",
            "## Changed Files",
            f"- changed_file: {data.get('path', '')}",
            f"- snapshot: {data.get('snapshot_path', '')}",
            f"- restore: {data.get('restore_hint', '')}",
            "",
        ]
    )
    redacted_summary = redact_value(summary)
    summary_text = redacted_summary.value
    if redacted_summary.applied:
        summary_text = summary_text.rstrip("\n") + "\n- redaction_applied: true\n"
    (run_dir / "summary.md").write_text(summary_text, encoding="utf-8")


def _is_within(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root))
    try:
        return os.path.commonpath([path_text, root_text]) == root_text
    except ValueError:
        return False
