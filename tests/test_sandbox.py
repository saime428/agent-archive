from pathlib import Path

import pytest

from agent.core.actions import ErrorCode
from agent.policy.sandbox import SandboxError, WorkspaceSandbox


def test_resolve_read_path_allows_workspace_file(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    assert sandbox.resolve_read_path("notes.txt") == target.resolve()


def test_resolve_read_path_rejects_parent_escape(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_read_path("../outside.txt")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_read_path_allows_explicit_external_when_enabled(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external.txt"
    workspace.mkdir()
    external.write_text("hello", encoding="utf-8")
    sandbox = WorkspaceSandbox(workspace, allow_external_read=True)

    assert sandbox.resolve_read_path(str(external)) == external.resolve()


def test_resolve_read_path_still_rejects_relative_escape_when_external_enabled(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = WorkspaceSandbox(workspace, allow_external_read=True)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_read_path("../external.txt")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_read_path_rejects_protected_runs_directory(tmp_path) -> None:
    protected_file = tmp_path / ".agent" / "runs" / "run_1" / "summary.md"
    protected_file.parent.mkdir(parents=True)
    protected_file.write_text("internal", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_read_path(".agent/runs/run_1/summary.md")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_read_path_rejects_workspace_secrets(tmp_path) -> None:
    secrets = tmp_path / ".agent" / "secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("TOKEN=secret\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_read_path(".agent/secrets.env")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_allows_workspace_file(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    assert sandbox.resolve_write_path("notes.txt") == (tmp_path / "notes.txt").resolve()


def test_resolve_write_path_rejects_parent_escape(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path("../outside.txt")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_allows_explicit_external_when_enabled(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external.txt"
    workspace.mkdir()
    sandbox = WorkspaceSandbox(workspace, allow_external_write=True)

    assert sandbox.resolve_write_path(str(external)) == external.resolve()


def test_resolve_write_path_rejects_protected_runs_directory(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path(".agent/runs/run_1/summary.md")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_rejects_workspace_secrets_file(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path(".agent/secrets.env")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_rejects_agent_internal_directory(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path(".agent/config.toml")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_rejects_git_directory(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path(".git/config")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION


def test_resolve_write_path_rejects_pycache_directory(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_write_path("__pycache__/cache.pyc")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION
