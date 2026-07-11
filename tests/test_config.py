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


def test_config_accepts_utf8_bom_files_written_by_windows_powershell(tmp_path) -> None:
    project_config = tmp_path / ".agent" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text('mode = "auto"\n', encoding="utf-8-sig")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.mode == "auto"
    assert diagnostics.loaded_files == (project_config,)


def test_max_consecutive_errors_defaults_to_three() -> None:
    assert AgentConfig().max_consecutive_errors == 3


def test_max_consecutive_errors_loads_from_project_config(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("max_consecutive_errors = 5\n", encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.max_consecutive_errors == 5
    assert diagnostics.warnings == []


def test_max_consecutive_errors_rejects_non_positive(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("max_consecutive_errors = 0\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")


def test_base_url_and_api_key_env_defaults() -> None:
    config = AgentConfig()

    assert config.base_url == ""
    assert config.api_key_env == "OPENAI_API_KEY"


def test_openai_compat_provider_is_valid(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\n',
        encoding="utf-8",
    )

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.provider == "openai-compat"
    assert config.base_url == "http://localhost:11434/v1"
    assert diagnostics.warnings == []


def test_base_url_rejects_non_string(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("base_url = 3\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")


def test_api_key_env_rejects_empty_string(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('api_key_env = " "\n', encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")


def test_native_tools_defaults_to_false() -> None:
    assert AgentConfig().native_tools is False


def test_native_tools_loads_from_project_config(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("native_tools = true\n", encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.native_tools is True
    assert diagnostics.warnings == []


def test_native_tools_rejects_non_boolean(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('native_tools = "yes"\n', encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")
