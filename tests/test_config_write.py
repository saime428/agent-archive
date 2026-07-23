from __future__ import annotations

import pytest

from agent.config import AgentConfig, load_config
from agent.config_write import remove_project_config_keys, save_project_config


def test_save_writes_project_config_atomically(tmp_path) -> None:
    path = save_project_config(tmp_path, {"model": "m2"})

    assert path == tmp_path / ".agent" / "config.toml"
    config, _diagnostics = load_config(tmp_path, home=tmp_path / "home")
    assert config.model == "m2"
    assert config.provider == AgentConfig().provider


def test_save_accepts_list_and_tuple_sequences(tmp_path) -> None:
    save_project_config(tmp_path, {"default_skills": ["a", "b"]})
    save_project_config(tmp_path, {"allowed_commands": ("git status",)})

    config, _diagnostics = load_config(tmp_path, home=tmp_path / "home")
    assert config.default_skills == ("a", "b")
    assert config.allowed_commands == ("git status",)


def test_save_strips_string_values(tmp_path) -> None:
    save_project_config(tmp_path, {"model": " m ", "default_skills": [" a "]})

    config, _diagnostics = load_config(tmp_path, home=tmp_path / "home")
    assert config.model == "m"
    assert config.default_skills == ("a",)


def test_save_rejects_unknown_key(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unknown config key"):
        save_project_config(tmp_path, {"nope": 1})

    assert not (tmp_path / ".agent" / "config.toml").exists()


def test_save_rejects_invalid_value_and_keeps_file(tmp_path) -> None:
    save_project_config(tmp_path, {"mode": "auto"})
    before = (tmp_path / ".agent" / "config.toml").read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        save_project_config(tmp_path, {"mode": "bogus"})

    assert (tmp_path / ".agent" / "config.toml").read_text(encoding="utf-8") == before


def test_save_rejects_danger_sandbox_and_never_approval(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot widen sandbox permissions"):
        save_project_config(tmp_path, {"sandbox": "danger-full-access"})
    with pytest.raises(ValueError, match="cannot disable approvals"):
        save_project_config(tmp_path, {"approval": "never"})

    assert not (tmp_path / ".agent" / "config.toml").exists()


def test_remove_deletes_key_and_falls_back(tmp_path) -> None:
    save_project_config(tmp_path, {"model": "m2"})

    remove_project_config_keys(tmp_path, ["model"])

    config, _diagnostics = load_config(tmp_path, home=tmp_path / "home")
    assert config.model == AgentConfig().model


def test_remove_missing_key_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="Key is not set in project config"):
        remove_project_config_keys(tmp_path, ["model"])
