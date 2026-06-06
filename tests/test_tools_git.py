from __future__ import annotations

import subprocess

from agent.core.actions import ErrorCode, parse_model_action
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.git import execute_git_tool


def _parse_git_action(context: RunContext, name: str, args: dict):
    return parse_model_action(
        {
            "message": f"Run {name}.",
            "action": {"name": name, "args": args},
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _init_repo(path) -> None:
    _git(path, "init")


def _commit_all(path, message: str = "initial") -> None:
    _git(path, "add", ".")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            "commit",
            "-m",
            message,
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_git_status_short_returns_short_status(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(context, "git_status", {"short": True})

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["exit_code"] == 0
    assert observation.data["stdout"] == "?? notes.txt\n"
    assert observation.data["stdout_truncated"] is False


def test_git_status_long_returns_status_text(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(context, "git_status", {"short": False})

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert "Untracked files" in observation.data["stdout"]
    assert "notes.txt" in observation.data["stdout"]


def test_git_diff_returns_worktree_diff(tmp_path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    _commit_all(tmp_path)
    target.write_text("new\n", encoding="utf-8")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(
        context,
        "git_diff",
        {"path": None, "cached": False, "max_bytes": None},
    )

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["exit_code"] == 0
    assert "-old" in observation.data["stdout"]
    assert "+new" in observation.data["stdout"]


def test_git_diff_filters_to_path(tmp_path) -> None:
    _init_repo(tmp_path)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old first\n", encoding="utf-8")
    second.write_text("old second\n", encoding="utf-8")
    _commit_all(tmp_path)
    first.write_text("new first\n", encoding="utf-8")
    second.write_text("new second\n", encoding="utf-8")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(
        context,
        "git_diff",
        {"path": "first.txt", "cached": False, "max_bytes": None},
    )

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert "first.txt" in observation.data["stdout"]
    assert "second.txt" not in observation.data["stdout"]


def test_git_diff_cached_returns_staged_diff(tmp_path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    _commit_all(tmp_path)
    target.write_text("staged\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.txt")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(
        context,
        "git_diff",
        {"path": None, "cached": True, "max_bytes": None},
    )

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert "-old" in observation.data["stdout"]
    assert "+staged" in observation.data["stdout"]


def test_git_diff_rejects_path_escape(tmp_path) -> None:
    _init_repo(tmp_path)
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(
        context,
        "git_diff",
        {"path": "../outside.txt", "cached": False, "max_bytes": None},
    )

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


def test_git_diff_truncates_stdout(tmp_path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    _commit_all(tmp_path)
    target.write_text("x" * 500 + "\n", encoding="utf-8")
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(
        context,
        "git_diff",
        {"path": None, "cached": False, "max_bytes": 80},
    )

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["stdout_truncated"] is True
    assert observation.data["stdout"].endswith("\n[truncated]")


def test_git_status_returns_tool_failed_outside_git_repo(tmp_path) -> None:
    context = RunContext.create("git", cwd=tmp_path, run_id="run_git")
    action = _parse_git_action(context, "git_status", {"short": True})

    observation = execute_git_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED
