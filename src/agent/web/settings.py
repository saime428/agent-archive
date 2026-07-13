from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.config import ConfigError, load_config
from agent.core.budget import truncate_text
from agent.core.memory import MemoryCandidate, MemoryEntry, MemoryStore
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.secrets import load_workspace_secrets
from agent.web.runs import build_failure_summary


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
            failed_runs += int(bool(build_failure_summary(detail.tool_calls)["failure_count"]))
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
