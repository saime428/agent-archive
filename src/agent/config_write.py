"""Managed project-config write path shared by the CLI and the Workbench."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent import _user_store
from agent.config import KNOWN_KEYS, ConfigError, normalize_value, validate_value

_SEQUENCE_KEYS = {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}


def save_project_config(workspace: Path, updates: dict[str, Any]) -> Path:
    prepared: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in KNOWN_KEYS:
            raise ValueError(f"Unknown config key: {key}.")
        if key in _SEQUENCE_KEYS and isinstance(value, (list, tuple)):
            value = tuple(item.strip() if isinstance(item, str) else item for item in value)
        elif isinstance(value, str):
            value = value.strip()
        if key == "sandbox" and value == "danger-full-access":
            raise ValueError(
                "project config cannot widen sandbox permissions; edit the global config by hand instead."
            )
        if key == "approval" and value == "never":
            raise ValueError(
                "project config cannot disable approvals; edit the global config by hand instead."
            )
        validate_value(key, value, None)
        prepared[key] = normalize_value(key, value)
    config_path = _project_config_path(workspace)
    existing = _read_project_config(config_path)
    existing.update(prepared)
    return _publish(config_path, existing)


def remove_project_config_keys(workspace: Path, keys: Iterable[str]) -> Path:
    config_path = _project_config_path(workspace)
    existing = _read_project_config(config_path)
    for key in keys:
        if key not in KNOWN_KEYS:
            raise ValueError(f"Unknown config key: {key}.")
        if key not in existing:
            raise ValueError(f"Key is not set in project config: {key}.")
        del existing[key]
    return _publish(config_path, existing)


def _project_config_path(workspace: Path) -> Path:
    return workspace.resolve() / ".agent" / "config.toml"


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


def _publish(config_path: Path, values: dict[str, Any]) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _user_store.atomic_replace_bytes(
            config_path.parent,
            config_path,
            _dump_toml(values).encode("utf-8"),
        )
    except _user_store.UserStoreError as exc:
        raise OSError(f"Could not save project config {config_path}.") from exc
    return config_path


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
