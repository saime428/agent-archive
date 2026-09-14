from __future__ import annotations

import os

import pytest

from agent.config import ConfigError
from agent.secrets import load_workspace_secrets


def test_load_workspace_secrets_sets_missing_env_without_overwriting(monkeypatch, tmp_path) -> None:
    secrets_path = tmp_path / ".agent" / "secrets.env"
    secrets_path.parent.mkdir()
    secrets_path.write_text(
        'DEEPSEEK_API_KEY="local-secret"\nEXISTING_KEY=from-file\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING_KEY", "from-env")

    loaded = load_workspace_secrets(tmp_path)

    assert loaded == secrets_path
    assert os.environ["DEEPSEEK_API_KEY"] == "local-secret"
    assert os.environ["EXISTING_KEY"] == "from-env"


def test_load_workspace_secrets_missing_file_is_noop(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    loaded = load_workspace_secrets(tmp_path)

    assert loaded is None
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_load_workspace_secrets_reports_invalid_utf8_without_content(tmp_path) -> None:
    path = tmp_path / ".agent" / "secrets.env"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"TOKEN=secret-value\n\xff")

    with pytest.raises(ConfigError) as exc_info:
        load_workspace_secrets(tmp_path)

    assert str(exc_info.value) == f"Could not read secrets file {path}."
    assert "secret-value" not in str(exc_info.value)
