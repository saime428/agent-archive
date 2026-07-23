from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.config import AgentConfig, ConfigDiagnostics, VALID_VALUES, load_config
from agent.config_write import save_project_config
from agent.core.budget import truncate_text
from agent.core.memory import MemoryCandidate, MemoryEntry, MemoryStore
from agent.core.run_store import RunStore, RunStoreError
from agent.core.tool_catalog import list_tool_infos
from agent.llm.factory import PROVIDER_REGISTRY, ProviderSpec
from agent.secrets import load_workspace_secrets
from agent.web.runs import build_failure_summary


def build_health_payload(workspace: Path) -> dict[str, Any]:
    load_workspace_secrets(workspace)
    loaded_config, config_payload = _load_config_payload(workspace)
    config = config_payload["config"]
    spec = PROVIDER_REGISTRY[loaded_config.provider]
    api_key_env = spec.api_key_env(loaded_config) if spec.api_key_env is not None else None
    api_key_present = bool(api_key_env and os.environ.get(api_key_env))
    deepseek_api_key_env = loaded_config.deepseek_api_key_env
    deepseek_api_key_present = bool(os.environ.get(deepseek_api_key_env))
    return {
        "status": "ok",
        "app": "agent-workbench",
        "workspace": str(workspace.resolve()),
        "provider": config["provider"],
        "model": config["model"],
        "mode": config["mode"],
        "deepseek_api_key_env": deepseek_api_key_env,
        "deepseek_api_key_present": deepseek_api_key_present,
        "base_url": str(config["base_url"]),
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "api_key_required": spec.api_key_required,
        "native_tools": bool(config["native_tools"]),
        "provider_notice": _provider_notice(spec, api_key_env, api_key_present, str(config["base_url"])),
        "settings_readiness": _build_settings_readiness(config_payload, spec, api_key_env, api_key_present),
        "workspace_risk": _build_workspace_risk(workspace.resolve()),
        "memory_review": _build_memory_review(workspace.resolve()),
    }


def _provider_notice(spec: ProviderSpec, api_key_env: str | None, api_key_present: bool, base_url: str) -> str:
    if spec.requires_base_url and not base_url.strip():
        return f"已选择 {spec.display_name}，但缺少 base_url。请在 .agent/config.toml 设置 base_url。"
    if spec.api_key_required and api_key_env and not api_key_present:
        return f"已选择 {spec.display_name}，但缺少 {api_key_env}。"
    return f"已选择 {spec.display_name}。"


def _build_settings_readiness(
    config_payload: dict[str, Any],
    spec: ProviderSpec,
    api_key_env: str | None,
    api_key_present: bool,
) -> dict[str, Any]:
    config = config_payload["config"]
    diagnostics = config_payload["diagnostics"]
    provider = str(config["provider"])
    warnings = list(diagnostics.get("warnings", []))
    checks: list[str] = []
    if spec.requires_base_url and not str(config["base_url"]).strip():
        status = "needs-base-url"
        checks.append(f"Set base_url before live {provider} runs.")
    elif spec.api_key_required and not api_key_present:
        status = "needs-api-key"
        checks.append(f"Set {api_key_env} before live {spec.display_name} runs.")
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
        "deepseek_api_key_present": bool(os.environ.get(str(config["deepseek_api_key_env"]))),
        "base_url": str(config["base_url"]),
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "api_key_required": spec.api_key_required,
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
    return _load_config_payload(workspace)[1]


def _load_config_payload(workspace: Path) -> tuple[AgentConfig, dict[str, Any]]:
    root = workspace.resolve()
    config, diagnostics = load_config(root)
    return config, _config_payload(root, config, diagnostics)


def _config_payload(workspace: Path, config: AgentConfig, diagnostics: ConfigDiagnostics) -> dict[str, Any]:
    config_record = asdict(config)
    for key in ("default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"):
        config_record[key] = list(config_record[key])
    return {
        "workspace": str(workspace),
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
    updates = _validated_config_updates(request)
    save_project_config(root, updates)
    payload = build_config_payload(root)
    payload["status"] = "ok"
    return payload


def _validated_config_updates(request: dict[str, Any]) -> dict[str, Any]:
    # 浏览器策略层：键白名单与 approval/sandbox 收紧；类型/枚举验证委托 config_write。
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
        if key == "provider" and value not in PROVIDER_REGISTRY:
            raise ValueError("provider must be fake, deepseek, or openai-compat.")
        if key == "mode" and (not isinstance(value, str) or value not in VALID_VALUES["mode"]):
            raise ValueError("mode must be step, guided, auto, or plan-first.")
        if key == "sandbox" and value not in {"read-only", "workspace-write"}:
            raise ValueError("sandbox must be read-only or workspace-write.")
        if key == "approval":
            if value == "never":
                raise ValueError("browser config cannot disable approvals.")
            if value not in {"risky-confirm", "always"}:
                raise ValueError("approval must be risky-confirm or always.")
        updates[key] = value
    return updates


def build_tools_payload() -> dict[str, Any]:
    return {"tools": [asdict(tool) for tool in list_tool_infos()]}
