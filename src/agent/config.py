from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

Mode = Literal["step", "guided", "auto", "plan-first"]
SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ApprovalMode = Literal["risky-confirm", "always", "never"]

VALID_VALUES = {
    "mode": {"step", "guided", "auto", "plan-first"},
    "sandbox": {"read-only", "workspace-write", "danger-full-access"},
    "approval": {"risky-confirm", "always", "never"},
}
KNOWN_KEYS = {"mode", "sandbox", "approval", "dry_run"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentConfig:
    mode: Mode = "guided"
    sandbox: SandboxMode = "workspace-write"
    approval: ApprovalMode = "risky-confirm"
    dry_run: bool = False


@dataclass(frozen=True)
class ConfigOverrides:
    mode: Mode | None = None
    sandbox: SandboxMode | None = None
    approval: ApprovalMode | None = None
    dry_run: bool | None = None


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
        config = replace(config, **{key: value})
    return config


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a TOML table.")
    return raw


def _validate_value(key: str, value: Any, path: Path) -> None:
    if key == "dry_run":
        if not isinstance(value, bool):
            raise ConfigError(f"Invalid value for dry_run in {path}: expected boolean.")
        return

    valid_values = VALID_VALUES[key]
    if value not in valid_values:
        expected = ", ".join(sorted(valid_values))
        raise ConfigError(f"Invalid value for {key} in {path}: {value!r}. Expected one of: {expected}.")


def _apply_overrides(config: AgentConfig, overrides: ConfigOverrides) -> AgentConfig:
    values = {
        "mode": overrides.mode,
        "sandbox": overrides.sandbox,
        "approval": overrides.approval,
        "dry_run": overrides.dry_run,
    }
    for key, value in values.items():
        if value is None:
            continue
        _validate_override(key, value)
        config = replace(config, **{key: value})
    return config


def _validate_override(key: str, value: Any) -> None:
    if key == "dry_run":
        if not isinstance(value, bool):
            raise ConfigError("Invalid CLI value for dry_run: expected boolean.")
        return
    valid_values = VALID_VALUES[key]
    if value not in valid_values:
        expected = ", ".join(sorted(valid_values))
        raise ConfigError(f"Invalid CLI value for {key}: {value!r}. Expected one of: {expected}.")
