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


def test_resolve_read_path_rejects_protected_runs_directory(tmp_path) -> None:
    protected_file = tmp_path / ".agent" / "runs" / "run_1" / "summary.md"
    protected_file.parent.mkdir(parents=True)
    protected_file.write_text("internal", encoding="utf-8")
    sandbox = WorkspaceSandbox(tmp_path)

    with pytest.raises(SandboxError) as exc_info:
        sandbox.resolve_read_path(".agent/runs/run_1/summary.md")

    assert exc_info.value.code == ErrorCode.SANDBOX_VIOLATION
