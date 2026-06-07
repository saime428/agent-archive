from __future__ import annotations

import pytest

from agent.config import (
    AgentConfig,
    ConfigError,
    ConfigOverrides,
    load_config,
)


def test_load_config_returns_defaults(tmp_path) -> None:
    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config == AgentConfig()
    assert config.provider == "fake"
    assert config.model == "deepseek-v4-flash"
    assert config.deepseek_api_key_env == "DEEPSEEK_API_KEY"
    assert diagnostics.warnings == []


def test_global_config_overrides_defaults(tmp_path) -> None:
    home = tmp_path / "home"
    global_config = home / ".agent" / "config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text(
        (
            'mode = "auto"\nsandbox = "read-only"\napproval = "always"\ndry_run = true\n'
            'provider = "deepseek"\nmodel = "deepseek-v4-pro"\ndeepseek_api_key_env = "CUSTOM_KEY"\n'
        ),
        encoding="utf-8",
    )

    config, diagnostics = load_config(tmp_path, home=home)

    assert config == AgentConfig(
        mode="auto",
        sandbox="read-only",
        approval="always",
        dry_run=True,
        provider="deepseek",
        model="deepseek-v4-pro",
        deepseek_api_key_env="CUSTOM_KEY",
    )
    assert diagnostics.warnings == []


def test_project_config_overrides_global_config(tmp_path) -> None:
    home = tmp_path / "home"
    global_config = home / ".agent" / "config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text('mode = "step"\n', encoding="utf-8")
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('mode = "auto"\n', encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=home)

    assert config.mode == "auto"
    assert diagnostics.warnings == []


def test_cli_overrides_file_config(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        'mode = "step"\nsandbox = "read-only"\napproval = "always"\ndry_run = false\n',
        encoding="utf-8",
    )

    config, diagnostics = load_config(
        tmp_path,
        home=tmp_path / "home",
        overrides=ConfigOverrides(
            mode="auto",
            sandbox="workspace-write",
            approval="risky-confirm",
            dry_run=True,
            provider="deepseek",
            model="deepseek-v4-pro",
        ),
    )

    assert config == AgentConfig(
        mode="auto",
        sandbox="workspace-write",
        approval="risky-confirm",
        dry_run=True,
        provider="deepseek",
        model="deepseek-v4-pro",
    )
    assert diagnostics.warnings == []


def test_project_config_cannot_set_danger_full_access(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('sandbox = "danger-full-access"\n', encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.sandbox == "workspace-write"
    assert diagnostics.warnings == [
        "Ignoring project config sandbox=danger-full-access because project config cannot widen sandbox permissions."
    ]


def test_project_config_cannot_set_approval_never(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('approval = "never"\n', encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.approval == "risky-confirm"
    assert diagnostics.warnings == [
        "Ignoring project config approval=never because project config cannot disable approvals."
    ]


def test_cli_can_explicitly_set_danger_full_access_and_approval_never(tmp_path) -> None:
    config, diagnostics = load_config(
        tmp_path,
        home=tmp_path / "home",
        overrides=ConfigOverrides(sandbox="danger-full-access", approval="never"),
    )

    assert config.sandbox == "danger-full-access"
    assert config.approval == "never"
    assert diagnostics.warnings == []


def test_unknown_config_key_adds_warning(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('surprise = true\nmode = "auto"\n', encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.mode == "auto"
    assert diagnostics.warnings == [f"Ignoring unknown config key surprise in {project_config}."]


def test_invalid_enum_value_raises_config_error(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('mode = "turbo"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path, home=tmp_path / "home")

    assert "Invalid value for mode" in str(exc_info.value)


def test_invalid_provider_raises_config_error(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('provider = "other"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path, home=tmp_path / "home")

    assert "Invalid value for provider" in str(exc_info.value)


def test_invalid_toml_raises_config_error(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text("mode = [", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path, home=tmp_path / "home")

    assert "Could not parse config file" in str(exc_info.value)
