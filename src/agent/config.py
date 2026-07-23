from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

Mode = Literal["step", "guided", "auto", "plan-first"]
SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ApprovalMode = Literal["risky-confirm", "always", "never"]
Provider = Literal["fake", "deepseek", "openai-compat"]

VALID_VALUES = {
    "provider": {"fake", "deepseek", "openai-compat"},
    "mode": {"step", "guided", "auto", "plan-first"},
    "sandbox": {"read-only", "workspace-write", "danger-full-access"},
    "approval": {"risky-confirm", "always", "never"},
}
KNOWN_KEYS = {
    "provider",
    "model",
    "deepseek_api_key_env",
    "base_url",
    "api_key_env",
    "default_skills",
    "allowed_commands",
    "memory_auto_write",
    "memory_max_items",
    "enabled_hooks",
    "blocking_hooks",
    "mode",
    "sandbox",
    "approval",
    "dry_run",
    "web_search_enabled",
    "computer_read_enabled",
    "max_consecutive_errors",
    "native_tools",
}
# 与 agent.core.hooks.BUILTIN_HOOKS 保持一致；契约测试锁定（config 保持叶子模块不 import core）。
KNOWN_HOOK_NAMES = frozenset({"audit", "before_tool_format", "fail"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentConfig:
    provider: Provider = "fake"
    model: str = "deepseek-v4-flash"
    deepseek_api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    default_skills: tuple[str, ...] = ("code-dev",)
    allowed_commands: tuple[str, ...] = ()
    memory_auto_write: bool = False
    memory_max_items: int = 5
    enabled_hooks: tuple[str, ...] = ()
    blocking_hooks: tuple[str, ...] = ()
    mode: Mode = "guided"
    sandbox: SandboxMode = "workspace-write"
    approval: ApprovalMode = "risky-confirm"
    dry_run: bool = False
    web_search_enabled: bool = False
    computer_read_enabled: bool = False
    max_consecutive_errors: int = 3
    native_tools: bool = False


@dataclass(frozen=True)
class ConfigOverrides:
    provider: Provider | None = None
    model: str | None = None
    deepseek_api_key_env: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    default_skills: tuple[str, ...] | None = None
    allowed_commands: tuple[str, ...] | None = None
    memory_auto_write: bool | None = None
    memory_max_items: int | None = None
    enabled_hooks: tuple[str, ...] | None = None
    blocking_hooks: tuple[str, ...] | None = None
    mode: Mode | None = None
    sandbox: SandboxMode | None = None
    approval: ApprovalMode | None = None
    dry_run: bool | None = None
    web_search_enabled: bool | None = None
    computer_read_enabled: bool | None = None
    max_consecutive_errors: int | None = None
    native_tools: bool | None = None


@dataclass(frozen=True)
class ConfigDiagnostics:
    global_config_path: Path
    project_config_path: Path
    loaded_files: tuple[Path, ...]
    warnings: list[str]


def load_config(
    cwd: Path,
    *,
    home: Path | None = None,
    overrides: ConfigOverrides | None = None,
) -> tuple[AgentConfig, ConfigDiagnostics]:
    workspace = cwd.resolve()
    home_dir = (home or Path.home()).resolve()
    global_config_path = home_dir / ".agent" / "config.toml"
    project_config_path = workspace / ".agent" / "config.toml"
    config = AgentConfig()
    loaded_files: list[Path] = []
    warnings: list[str] = []

    if global_config_path.exists():
        config = _apply_file_config(config, global_config_path, source="global", warnings=warnings)
        loaded_files.append(global_config_path)
    if project_config_path.exists():
        config = _apply_file_config(config, project_config_path, source="project", warnings=warnings)
        loaded_files.append(project_config_path)

    if overrides is not None:
        config = _apply_overrides(config, overrides)

    for key_name, names in (("enabled_hooks", config.enabled_hooks), ("blocking_hooks", config.blocking_hooks)):
        for name in names:
            if name not in KNOWN_HOOK_NAMES:
                known = ", ".join(sorted(KNOWN_HOOK_NAMES))
                warnings.append(f"Unknown hook {name!r} in {key_name}; known hooks: {known}.")
    for name in config.blocking_hooks:
        if name in KNOWN_HOOK_NAMES and name not in config.enabled_hooks:
            warnings.append(f"Blocking hook {name!r} is not in enabled_hooks and will never run.")

    diagnostics = ConfigDiagnostics(
        global_config_path=global_config_path,
        project_config_path=project_config_path,
        loaded_files=tuple(loaded_files),
        warnings=warnings,
    )
    return config, diagnostics


def _apply_file_config(
    config: AgentConfig,
    path: Path,
    *,
    source: Literal["global", "project"],
    warnings: list[str],
) -> AgentConfig:
    values = _read_config_file(path)
    for key in values:
        if key not in KNOWN_KEYS:
            warnings.append(f"Ignoring unknown config key {key} in {path}.")

    for key in KNOWN_KEYS:
        if key not in values:
            continue
        value = values[key]
        _validate_value(key, value, path)
        if source == "project" and key == "sandbox" and value == "danger-full-access":
            warnings.append(
                "Ignoring project config sandbox=danger-full-access because project config cannot widen sandbox permissions."
            )
            continue
        if source == "project" and key == "approval" and value == "never":
            warnings.append("Ignoring project config approval=never because project config cannot disable approvals.")
            continue
        config = replace(config, **{key: _normalize_value(key, value)})
    return config


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a TOML table.")
    return raw


def _apply_overrides(config: AgentConfig, overrides: ConfigOverrides) -> AgentConfig:
    values = {
        "provider": overrides.provider,
        "model": overrides.model,
        "deepseek_api_key_env": overrides.deepseek_api_key_env,
        "base_url": overrides.base_url,
        "api_key_env": overrides.api_key_env,
        "default_skills": overrides.default_skills,
        "allowed_commands": overrides.allowed_commands,
        "memory_auto_write": overrides.memory_auto_write,
        "memory_max_items": overrides.memory_max_items,
        "enabled_hooks": overrides.enabled_hooks,
        "blocking_hooks": overrides.blocking_hooks,
        "mode": overrides.mode,
        "sandbox": overrides.sandbox,
        "approval": overrides.approval,
        "dry_run": overrides.dry_run,
        "web_search_enabled": overrides.web_search_enabled,
        "computer_read_enabled": overrides.computer_read_enabled,
        "max_consecutive_errors": overrides.max_consecutive_errors,
        "native_tools": overrides.native_tools,
    }
    for key, value in values.items():
        if value is None:
            continue
        _validate_value(key, value, None)
        config = replace(config, **{key: _normalize_value(key, value)})
    return config


def _validate_value(key: str, value: Any, path: Path | None) -> None:
    cli = path is None
    sequence_type = tuple if cli else list
    if key in {"dry_run", "memory_auto_write", "web_search_enabled", "computer_read_enabled", "native_tools"}:
        if not isinstance(value, bool):
            raise _invalid_config_value(key, "expected boolean", path)
        return
    if key in {"memory_max_items", "max_consecutive_errors"}:
        if not isinstance(value, int) or value <= 0:
            raise _invalid_config_value(key, "expected positive integer", path)
        return
    if key in {"model", "deepseek_api_key_env", "api_key_env"}:
        if not isinstance(value, str) or not value.strip():
            raise _invalid_config_value(key, "expected non-empty string", path)
        return
    if key == "base_url":
        if not isinstance(value, str):
            raise _invalid_config_value(key, "expected string", path)
        return
    if key in {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}:
        type_name = "tuple" if cli else "list"
        if not isinstance(value, sequence_type) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise _invalid_config_value(key, f"expected {type_name} of non-empty strings", path)
        return
    valid_values = VALID_VALUES[key]
    if value not in valid_values:
        expected = ", ".join(sorted(valid_values))
        raise _invalid_config_value(key, f"{value!r}. Expected one of: {expected}", path)


def _invalid_config_value(key: str, message: str, path: Path | None) -> ConfigError:
    if path is None:
        return ConfigError(f"Invalid CLI value for {key}: {message}.")
    return ConfigError(f"Invalid value for {key} in {path}: {message}.")


def _normalize_value(key: str, value: Any) -> Any:
    if key in {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}:
        return tuple(value)
    return value
