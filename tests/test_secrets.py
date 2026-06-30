from __future__ import annotations

import os

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
