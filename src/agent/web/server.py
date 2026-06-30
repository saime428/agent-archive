from __future__ import annotations

import difflib
import json
import mimetypes
import os
import shutil
import subprocess
import tomllib
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
from agent.core.memory import MemoryCandidate, MemoryEntry, MemoryStore
from agent.core.redaction import redact_record, redact_value
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DeepSeekError
from agent.llm.factory import make_llm
from agent.secrets import load_workspace_secrets
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
                if path == "/api/chats":
                    self._send_json(build_chats_payload(root))
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
                if path.startswith("/api/chats/"):
                    session_id = path.rsplit("/", 1)[-1]
                    self._send_json(build_chat_payload(root, session_id))
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

    return WorkbenchHandler


def build_health_payload(workspace: Path) -> dict[str, Any]:
    load_workspace_secrets(workspace)
    config_payload = build_config_payload(workspace)
    config = config_payload["config"]
    api_key_env = str(config["deepseek_api_key_env"])
    api_key_present = bool(os.environ.get(api_key_env))
    return {
        "status": "ok",
        "app": "agent-workbench",
        "workspace": str(workspace.resolve()),
        "provider": config["provider"],
        "model": config["model"],
        "mode": config["mode"],
        "deepseek_api_key_env": api_key_env,
        "deepseek_api_key_present": api_key_present,
        "provider_notice": _provider_notice(str(config["provider"]), api_key_env, api_key_present),
        "settings_readiness": _build_settings_readiness(config_payload, api_key_present),
        "workspace_risk": _build_workspace_risk(workspace.resolve()),
        "memory_review": _build_memory_review(workspace.resolve()),
    }


def _provider_notice(provider: str, api_key_env: str, api_key_present: bool) -> str:
    if provider != "deepseek":
        return 'Workbench is using FakeLLM. Set provider = "deepseek" in .agent/config.toml to use DeepSeek.'
    if not api_key_present:
        return f"DeepSeek provider is selected, but {api_key_env} is missing."
    return "DeepSeek provider is selected."


def _build_settings_readiness(config_payload: dict[str, Any], api_key_present: bool) -> dict[str, Any]:
    config = config_payload["config"]
    diagnostics = config_payload["diagnostics"]
    provider = str(config["provider"])
    warnings = list(diagnostics.get("warnings", []))
    checks: list[str] = []
    if provider == "deepseek" and not api_key_present:
        status = "needs-api-key"
        checks.append("Set DEEPSEEK_API_KEY before live DeepSeek runs.")
    elif warnings:
        status = "warnings"
        checks.append("Review config warnings before relying on live settings.")
    else:
        status = "ready"
        checks.append("Settings are readable.")
    return {
        "mode": "read-only",
        "status": status,
        "provider": provider,
        "model": str(config["model"]),
        "deepseek_api_key_env": str(config["deepseek_api_key_env"]),
        "deepseek_api_key_present": api_key_present,
        "loaded_files": list(diagnostics.get("loaded_files", [])),
        "warnings": warnings,
        "checks": checks,
    }


def _build_workspace_risk(workspace: Path) -> dict[str, Any]:
    uncommitted_files = _git_status_short(workspace)
    failed_runs = 0
    snapshot_count = 0
    try:
        store = RunStore(workspace)
        for run in store.list_runs(limit=20):
            detail = store.show_run(run.run_id)
            failed_runs += int(bool(_build_failure_summary(detail.tool_calls)["failure_count"]))
            snapshot_count += len(detail.snapshots)
    except RunStoreError:
        pass

    signals = {
        "uncommitted_files": len(uncommitted_files),
        "failed_runs": failed_runs,
        "snapshots": snapshot_count,
    }
    checks: list[str] = []
    if failed_runs:
        checks.append("Review failed recent runs.")
    if uncommitted_files:
        checks.append("Review uncommitted files before running or approving writes.")
    if snapshot_count:
        checks.append("Review snapshots before restoring or overwriting files.")

    if failed_runs:
        risk_level = "attention"
        summary = f"{failed_runs} failed recent run(s), {len(uncommitted_files)} uncommitted file(s), {snapshot_count} snapshot(s)."
    elif uncommitted_files or snapshot_count:
        risk_level = "medium"
        summary = f"{len(uncommitted_files)} uncommitted file(s), {snapshot_count} snapshot(s), no failed recent runs."
    else:
        risk_level = "low"
        summary = "No failed recent runs, uncommitted files, or snapshots detected."
        checks.append("No workspace risk action needed.")

    return {
        "mode": "read-only",
        "risk_level": risk_level,
        "summary": summary,
        "signals": signals,
        "uncommitted_files": uncommitted_files[:20],
        "checks": checks,
    }


def _git_status_short(workspace: Path) -> list[str]:
    if shutil.which("git") is None:
        return []
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _build_memory_review(workspace: Path) -> dict[str, Any]:
    try:
        store = MemoryStore(workspace)
        candidates = [item for item in store.list_candidates() if item.status == "pending"]
        entries = store.list_entries()
    except (OSError, TypeError, ValueError):
        return {
            "mode": "read-only",
            "pending_count": 0,
            "active_count": 0,
            "candidates": [],
            "entries": [],
            "checks": ["Memory store could not be read."],
        }

    checks: list[str] = []
    if candidates:
        checks.append("Review pending memory candidates")
    if entries:
        checks.append("Review active memory entries before relying on memory")
    if not checks:
        checks.append("No memory review action needed")

    return {
        "mode": "read-only",
        "pending_count": len(candidates),
        "active_count": len(entries),
        "candidates": [_memory_candidate_payload(item) for item in candidates[:10]],
        "entries": [_memory_entry_payload(item) for item in entries[:10]],
        "checks": checks,
    }


def _memory_candidate_payload(candidate: MemoryCandidate) -> dict[str, str]:
    return {
        "candidate_id": candidate.candidate_id,
        "source_run_id": candidate.source_run_id,
        "source_excerpt": truncate_text(candidate.source_excerpt, 300).value,
        "created_at": candidate.created_at,
        "status": candidate.status,
    }


def _memory_entry_payload(entry: MemoryEntry) -> dict[str, str | None]:
    return {
        "entry_id": entry.entry_id,
        "source_run_id": entry.source_run_id,
        "source_excerpt": truncate_text(entry.source_excerpt, 300).value,
        "created_at": entry.created_at,
        "status": entry.status,
        "supersedes": entry.supersedes,
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


def build_save_config_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    root = workspace.resolve()
    config_path = root / ".agent" / "config.toml"
    existing = _read_project_config(config_path)
    updates = _validated_config_updates(request)
    existing.update(updates)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_dump_toml(existing), encoding="utf-8")
    payload = build_config_payload(root)
    payload["status"] = "ok"
    return payload


def build_chats_payload(workspace: Path, *, limit: int = 30) -> dict[str, Any]:
    root = workspace.resolve()
    chats_root = root / ".agent" / "chats"
    states: list[ConversationState] = []
    if chats_root.is_dir():
        for session_dir in chats_root.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                states.append(ConversationState.load(root, session_dir.name))
            except (OSError, ValueError, KeyError, json.JSONDecodeError, TypeError):
                continue
    states.sort(key=lambda item: item.updated_at, reverse=True)
    return {
        "workspace": str(root),
        "chats": [_chat_list_item(state) for state in states[:limit]],
    }


def build_chat_payload(workspace: Path, session_id: str) -> dict[str, Any]:
    state = ConversationState.load(workspace.resolve(), session_id)
    return {
        "session_id": state.session_id,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "turn_count": len(state.turns),
        "turns": [asdict(turn) for turn in state.turns],
    }


def _chat_list_item(state: ConversationState) -> dict[str, Any]:
    latest = state.turns[-1] if state.turns else None
    return {
        "session_id": state.session_id,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "turn_count": len(state.turns),
        "latest_user": latest.user if latest else "",
        "latest_final": latest.final if latest else "",
        "status": latest.status if latest else "empty",
    }


def _read_project_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse config file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a TOML table.")
    return dict(raw)


def _validated_config_updates(request: dict[str, Any]) -> dict[str, Any]:
    allowed = {"provider", "model", "sandbox", "approval", "dry_run", "default_skills"}
    updates: dict[str, Any] = {}
    for key, value in request.items():
        if key not in allowed:
            continue
        if key == "provider":
            if value not in {"fake", "deepseek"}:
                raise ValueError("provider must be fake or deepseek.")
            updates[key] = value
        elif key == "model":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("model must be a non-empty string.")
            updates[key] = value.strip()
        elif key == "sandbox":
            if value not in {"read-only", "workspace-write"}:
                raise ValueError("sandbox must be read-only or workspace-write.")
            updates[key] = value
        elif key == "approval":
            if value == "never":
                raise ValueError("browser config cannot disable approvals.")
            if value not in {"risky-confirm", "always"}:
                raise ValueError("approval must be risky-confirm or always.")
            updates[key] = value
        elif key == "dry_run":
            if not isinstance(value, bool):
                raise ValueError("dry_run must be a boolean.")
            updates[key] = value
        elif key == "default_skills":
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError("default_skills must be a list of non-empty strings.")
            updates[key] = [item.strip() for item in value]
    return updates


def _dump_toml(values: dict[str, Any]) -> str:
    lines = [f"{key} = {_toml_value(value)}" for key, value in values.items()]
    return "\n".join(lines) + ("\n" if lines else "")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError(f"Unsupported config value type: {type(value).__name__}")


def build_tools_payload() -> dict[str, Any]:
    return {"tools": [asdict(tool) for tool in list_tool_infos()]}


def build_runs_payload(workspace: Path, *, limit: int = 20) -> dict[str, Any]:
    store = RunStore(workspace.resolve())
    runs = store.list_runs(limit=limit)
    return {
        "workspace": str(workspace.resolve()),
        "runs": [
            _build_run_list_item(store, run)
            for run in runs
        ],
    }


def _build_run_list_item(store: RunStore, run: Any) -> dict[str, Any]:
    item = {
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "summary_path": str(run.summary_path),
        "tool_calls_path": str(run.tool_calls_path),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "status": "unknown",
        "risk_level": "attention",
    }
    try:
        detail = store.show_run(run.run_id)
    except RunStoreError:
        return item

    review = _build_task_review(detail.tool_calls, detail.snapshots)
    failure = _build_failure_summary(detail.tool_calls)
    workflow = _build_workflow_hints(review)
    item["status"] = _summary_field(detail.summary, "status") or "unknown"
    item["risk_level"] = _build_patch_review(review, workflow, failure)["risk_level"]
    return item


def _summary_field(summary: str, name: str) -> str | None:
    prefix = f"- {name}: "
    for line in summary.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


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
    load_workspace_secrets(root)
    config, diagnostics = load_config(root)
    state = ConversationState.load(root, session_id) if session_id else ConversationState.create(root)
    session = ChatSession(cwd=root, llm=make_llm(config), config=config, state=state)
    result = session.run_turn(message.strip(), approval_handler=_approve_once_handler() if approve_once else None)
    turn = session.state.turns[-1]
    error = result.observation.error
    error_code = str(error.code) if error is not None else None
    repair_count = _repair_count(result.observations)
    return {
        "session_id": session.state.session_id,
        "turn_count": len(session.state.turns),
        "run_id": turn.run_id,
        "status": turn.status,
        "completed": turn.completed,
        "display_status": _display_status(turn.completed, error_code, turn.status, turn.terminal_reason),
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
        "repair_count": repair_count,
        "has_repair_noise": repair_count > 0,
    }


def _repair_count(observations: list[Any]) -> int:
    count = 0
    for observation in observations[:-1]:
        error = getattr(observation, "error", None)
        details = getattr(error, "details", None)
        if isinstance(details, dict) and "repair_attempt" in details:
            count += 1
    return count


def _display_status(completed: bool, error_code: str | None, status: str, terminal_reason: str) -> str:
    if completed:
        return "completed"
    if terminal_reason == "ask_user":
        return "ask_user"
    if error_code == "APPROVAL_REQUIRED":
        return "approval_required"
    if status == "error":
        return "error"
    return status


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
    review = _build_task_review(detail.tool_calls, detail.snapshots)
    failure = _build_failure_summary(detail.tool_calls)
    workflow = _build_workflow_hints(review)
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
        "review": review,
        "workflow": workflow,
        "failure": failure,
        "patch_review": _build_patch_review(review, workflow, failure),
        "recovery": _build_failure_recovery(review, workflow, failure),
        "replay": _build_run_replay(detail.tool_calls),
    }


def _build_task_review(tool_calls: list[Any], snapshots: list[dict[str, str]]) -> dict[str, Any]:
    latest_action = "none"
    last_observation_summary = "No observation recorded."
    changed_files: list[str] = []

    for call in tool_calls:
        if not call.valid or not call.data:
            continue
        action = call.data.get("action")
        if isinstance(action, dict):
            inner_action = action.get("action")
            if isinstance(inner_action, dict):
                latest_action = str(inner_action.get("name") or latest_action)
                args = inner_action.get("args")
                if isinstance(args, dict):
                    raw_changed_files = args.get("changed_files")
                    if isinstance(raw_changed_files, list):
                        changed_files.extend(str(path) for path in raw_changed_files if path)
        observation = call.data.get("observation")
        if isinstance(observation, dict):
            last_observation_summary = str(observation.get("summary") or last_observation_summary)

    changed_files.extend(str(snapshot.get("path")) for snapshot in snapshots if snapshot.get("path"))
    unique_changed_files = list(dict.fromkeys(changed_files))
    if unique_changed_files:
        manual_checks = ["Open the changed files and review the saved summary."]
    else:
        manual_checks = ["Review the summary and trace for the final status."]
    if snapshots:
        manual_checks.append("Use Show diff before Restore when checking snapshot-backed changes.")

    return {
        "latest_action": latest_action,
        "last_observation_summary": last_observation_summary,
        "changed_files": unique_changed_files,
        "snapshot_count": len(snapshots),
        "manual_checks": manual_checks,
    }


def _build_workflow_hints(review: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(path) for path in review.get("changed_files", []) if path]
    commands: list[str] = []
    if any(path.startswith("src/agent/web/") or path == "tests/test_ui.py" for path in changed_files):
        commands.append("python -m pytest tests/test_ui.py -q")
    if any(path == "README.md" or path.startswith("docs/") or path == "tests/test_docs.py" for path in changed_files):
        commands.append("python -m pytest tests/test_docs.py -q")
    if any(path.endswith(".py") for path in changed_files):
        commands.append("python -m pytest -q")
    if changed_files:
        commands.append("git diff --check")
    if not commands:
        commands.append("Review the summary and trace before taking action.")

    return {
        "mode": "read-only",
        "verification_commands": list(dict.fromkeys(commands)),
        "review_steps": [
            "Open changed files from Task Review.",
            "Run the suggested verification commands before committing.",
        ],
    }


def _build_failure_summary(tool_calls: list[Any]) -> dict[str, Any]:
    failures = []
    for call in tool_calls:
        failure = _failure_from_tool_call(call)
        if failure is not None:
            failures.append(failure)

    if not failures:
        return {
            "status": "clear",
            "failure_count": 0,
            "latest_failure": None,
            "next_checks": ["No failed observations recorded for this run."],
        }

    return {
        "status": "failed",
        "failure_count": len(failures),
        "latest_failure": failures[-1],
        "next_checks": [
            "Read the failed observation summary.",
            "Inspect the trace around the failed action.",
            "Use Workflow Hints before changing code.",
        ],
    }


def _build_patch_review(
    review: dict[str, Any],
    workflow: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    commands = list(workflow.get("verification_commands", []))
    changed_files = list(review.get("changed_files", []))
    snapshot_count = int(review.get("snapshot_count") or 0)

    if failure.get("failure_count"):
        return {
            "mode": "read-only",
            "risk_level": "attention",
            "summary": "Failed observations need review before patching.",
            "checks": [
                "Read Failure Summary before changing code.",
                "Inspect the trace around the failed action.",
                "Run verification commands only from a terminal.",
            ],
            "verification_commands": commands,
            "next_action": "Resolve or explain the failed observation before patching.",
        }

    if changed_files or snapshot_count:
        checks = ["Open changed files from Task Review."]
        if snapshot_count:
            checks.append("Use Show diff before Restore when checking snapshots.")
        checks.append("Run suggested verification commands from Workflow Hints.")
        return {
            "mode": "read-only",
            "risk_level": "medium",
            "summary": f"{len(changed_files)} changed file(s), {snapshot_count} snapshot(s), no failed observations.",
            "checks": checks,
            "verification_commands": commands,
            "next_action": "Review changes and run suggested verification commands from a terminal.",
        }

    return {
        "mode": "read-only",
        "risk_level": "low",
        "summary": "No failed observations or changed files recorded.",
        "checks": ["Review the summary and trace before taking action."],
        "verification_commands": commands,
        "next_action": "No patch review action needed.",
    }


def _build_failure_recovery(
    review: dict[str, Any],
    workflow: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    commands = list(workflow.get("verification_commands", []))
    snapshot_count = int(review.get("snapshot_count") or 0)
    rollback_available = snapshot_count > 0
    latest_failure = failure.get("latest_failure")

    if failure.get("failure_count"):
        steps = [
            "Inspect the failed action in Trace.",
            "Read Failure Summary before changing files.",
        ]
        if rollback_available:
            steps.append("Use Show diff before Restore when checking snapshots.")
        else:
            steps.append("Check the workspace manually before retrying.")
        return {
            "mode": "read-only",
            "status": "needs-attention",
            "rollback_available": rollback_available,
            "summary": "Failed observations need a recovery decision before more changes.",
            "latest_failure": latest_failure,
            "steps": steps,
            "checks": [
                "Do not retry tools from the browser.",
                "Run verification from a terminal after patching.",
            ],
            "verification_commands": commands,
            "next_action": "Inspect the failure, then patch or retry from a terminal workflow.",
        }

    if rollback_available:
        return {
            "mode": "read-only",
            "status": "snapshot-review",
            "rollback_available": True,
            "summary": f"{snapshot_count} snapshot(s) are available for manual review.",
            "latest_failure": None,
            "steps": ["Open Snapshots and use Show diff before any restore."],
            "checks": ["Restore only after confirming the diff."],
            "verification_commands": commands,
            "next_action": "Review snapshots before making further file changes.",
        }

    return {
        "mode": "read-only",
        "status": "clear",
        "rollback_available": False,
        "summary": "No failed observations or rollback snapshots recorded.",
        "latest_failure": None,
        "steps": ["No recovery action needed."],
        "checks": ["Review the summary and trace before taking action."],
        "verification_commands": commands,
        "next_action": "No recovery action needed.",
    }


def _build_run_replay(tool_calls: list[Any]) -> dict[str, Any]:
    steps = [_replay_step_from_tool_call(call) for call in tool_calls]
    return {
        "mode": "read-only",
        "step_count": len(steps),
        "steps": steps,
    }


def _replay_step_from_tool_call(call: Any) -> dict[str, Any]:
    if not call.valid or not call.data:
        return {
            "line_number": call.line_number,
            "phase": "parse",
            "action": "invalid",
            "status": "invalid",
            "summary": call.error or "Invalid tool call log record.",
            "terminal": True,
            "policy_decision": "",
        }

    action = call.data.get("action")
    inner_action = action.get("action") if isinstance(action, dict) else None
    observation = call.data.get("observation")
    trace = call.data.get("trace")
    return {
        "line_number": call.line_number,
        "phase": str(trace.get("phase") or "action") if isinstance(trace, dict) else "action",
        "action": str(inner_action.get("name") or "unknown") if isinstance(inner_action, dict) else "unknown",
        "status": str(observation.get("status") or "unknown") if isinstance(observation, dict) else "unknown",
        "summary": str(observation.get("summary") or "No observation summary.") if isinstance(observation, dict) else "No observation summary.",
        "terminal": bool(trace.get("terminal")) if isinstance(trace, dict) else False,
        "policy_decision": str(trace.get("policy_decision") or "") if isinstance(trace, dict) else "",
    }


def _failure_from_tool_call(call: Any) -> dict[str, Any] | None:
    if not call.valid or not call.data:
        return {
            "line_number": call.line_number,
            "action": "invalid",
            "status": "invalid",
            "summary": call.error or "Invalid tool call log record.",
            "error_code": "INVALID_LOG_RECORD",
        }

    action = call.data.get("action")
    action_name = "unknown"
    if isinstance(action, dict):
        inner_action = action.get("action")
        if isinstance(inner_action, dict):
            action_name = str(inner_action.get("name") or action_name)

    observation = call.data.get("observation")
    if not isinstance(observation, dict):
        return None
    status = str(observation.get("status") or "")
    if status == "ok":
        return None

    error = observation.get("error")
    error_code = ""
    error_message = ""
    if isinstance(error, dict):
        error_code = str(error.get("code") or "")
        error_message = str(error.get("message") or "")
    summary = str(observation.get("summary") or error_message or "No failure summary.")
    return {
        "line_number": call.line_number,
        "action": action_name,
        "status": status or "error",
        "summary": summary,
        "error_code": error_code,
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
