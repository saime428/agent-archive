from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import threading
import tomllib
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent.config import ConfigError, load_config
from agent.core.budget import truncate_text
from agent.core.memory import MemoryCandidate, MemoryEntry, MemoryStore
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.llm.deepseek import DeepSeekError
from agent.secrets import load_workspace_secrets
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
    build_failure_summary as _build_failure_summary,
    build_run_detail_payload as _build_run_detail_payload,
    build_runs_payload as _build_runs_payload,
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


def build_health_payload(workspace: Path) -> dict[str, Any]:
    load_workspace_secrets(workspace)
    config_payload = build_config_payload(workspace)
    config = config_payload["config"]
    api_key_env = str(config["deepseek_api_key_env"])
    api_key_present = bool(os.environ.get(api_key_env))
    notice_api_key_env = api_key_env
    notice_api_key_present = api_key_present
    if str(config["provider"]) == "openai-compat":
        notice_api_key_env = str(config["api_key_env"])
        notice_api_key_present = bool(os.environ.get(notice_api_key_env))
    return {
        "status": "ok",
        "app": "agent-workbench",
        "workspace": str(workspace.resolve()),
        "provider": config["provider"],
        "model": config["model"],
        "mode": config["mode"],
        "deepseek_api_key_env": api_key_env,
        "deepseek_api_key_present": api_key_present,
        "base_url": str(config["base_url"]),
        "api_key_env": str(config["api_key_env"]),
        "native_tools": bool(config["native_tools"]),
        "provider_notice": _provider_notice(
            str(config["provider"]), notice_api_key_env, notice_api_key_present, str(config["base_url"])
        ),
        "settings_readiness": _build_settings_readiness(config_payload, api_key_present),
        "workspace_risk": _build_workspace_risk(workspace.resolve()),
        "memory_review": _build_memory_review(workspace.resolve()),
    }


def _provider_notice(provider: str, api_key_env: str, api_key_present: bool, base_url: str = "") -> str:
    if provider == "openai-compat":
        if not base_url:
            return "已选择 OpenAI 兼容 Provider，但缺少 base_url。请在 .agent/config.toml 设置 base_url。"
        if not api_key_present:
            return f"已选择 OpenAI 兼容 Provider，但缺少 {api_key_env}。"
        return "已选择 OpenAI 兼容 Provider。"
    if provider != "deepseek":
        return '当前使用 FakeLLM。要使用 DeepSeek，请在 .agent/config.toml 设置 provider = "deepseek"。'
    if not api_key_present:
        return f"已选择 DeepSeek，但缺少 {api_key_env}。"
    return "已选择 DeepSeek。"


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
        "base_url": str(config["base_url"]),
        "api_key_env": str(config["api_key_env"]),
        "native_tools": bool(config["native_tools"]),
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
    for key in ("default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"):
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
    allowed = {
        "provider",
        "model",
        "mode",
        "sandbox",
        "approval",
        "dry_run",
        "web_search_enabled",
        "computer_read_enabled",
        "native_tools",
        "default_skills",
    }
    updates: dict[str, Any] = {}
    for key, value in request.items():
        if key not in allowed:
            continue
        if key == "provider":
            if value not in {"fake", "deepseek", "openai-compat"}:
                raise ValueError("provider must be fake, deepseek, or openai-compat.")
            updates[key] = value
        elif key == "model":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("model must be a non-empty string.")
            updates[key] = value.strip()
        elif key == "mode":
            if not isinstance(value, str) or value not in {"step", "guided", "auto", "plan-first"}:
                raise ValueError("mode must be step, guided, auto, or plan-first.")
            updates[key] = value
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
        elif key == "web_search_enabled":
            if not isinstance(value, bool):
                raise ValueError("web_search_enabled must be a boolean.")
            updates[key] = value
        elif key == "computer_read_enabled":
            if not isinstance(value, bool):
                raise ValueError("computer_read_enabled must be a boolean.")
            updates[key] = value
        elif key == "native_tools":
            if not isinstance(value, bool):
                raise ValueError("native_tools must be a boolean.")
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


def _query_value(query: str, key: str) -> str | None:
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        if unquote(name) == key:
            return unquote(value)
    return None
