from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent.core.actions import ActionCall, InternalAction
from agent.core.budget import ContextBudget
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.git import execute_git_tool


MAX_STATUS_ENTRIES = 1_000
MAX_STATUS_BYTES = 1_048_576
GIT_TIMEOUT_SECONDS = 30
_CONFLICT_STATUSES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def build_git_status_payload(workspace: Path) -> dict[str, Any]:
    root = workspace.resolve()
    state = _repository_state(root)
    if not state["is_repository"]:
        return {**state, "entries": [], "entry_count": 0, "truncated": False}

    completed = _run_git(
        root,
        "-c",
        "core.fsmonitor=false",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=dirty",
    )
    entries, truncated = _parse_status(completed.stdout)
    return {
        **state,
        "entries": entries,
        "entry_count": len(entries),
        "truncated": truncated,
    }


def build_git_diff_payload(workspace: Path, path: str | None, area: str | None) -> dict[str, Any]:
    if area not in {"staged", "unstaged"}:
        raise ValueError("area must be staged or unstaged.")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required.")
    if "\0" in path:
        raise ValueError("path must not contain NUL bytes.")
    if len(path) > 4_096:
        raise ValueError("path must be at most 4096 characters.")
    if Path(path).is_absolute():
        raise ValueError("path must be relative to the workspace.")

    root = workspace.resolve()
    state = _repository_state(root)
    if not state["is_repository"]:
        raise ValueError(f"Git diff is unavailable: {state['reason']}.")

    context = RunContext.create("Workbench Git diff", cwd=root)
    action = InternalAction(
        run_id=context.run_id,
        action_id="act_000001",
        created_at=context.created_at,
        message="Workbench Git diff.",
        action=ActionCall(
            name="git_diff",
            args={
                "path": path,
                "cached": area == "staged",
                "max_bytes": ContextBudget().git_output_chars,
            },
        ),
    )
    observation = execute_git_tool(
        action,
        context,
        WorkspaceSandbox(root),
        observation_index=1,
    )
    if observation.status != "ok" or observation.data is None:
        if observation.error is None:
            raise ValueError("Git diff failed.")
        raise ValueError(f"{observation.error.code.value}: {observation.error.message}")
    return {
        "path": observation.data["argv"][-1],
        "area": area,
        "diff": observation.data["stdout"],
        "truncated": observation.data["stdout_truncated"],
    }


def _repository_state(root: Path) -> dict[str, Any]:
    if shutil.which("git") is None:
        return {"git_available": False, "is_repository": False, "reason": "git_unavailable"}

    completed = _run_git(root, "rev-parse", "--show-toplevel", allow_not_repository=True)
    if completed.returncode != 0:
        if b"not a git repository" in completed.stderr.lower():
            return {"git_available": True, "is_repository": False, "reason": "not_repository"}
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git command exited with code {completed.returncode}: {stderr[:1_000]}")
    try:
        top_level = Path(completed.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except UnicodeDecodeError as exc:
        raise ValueError("Git repository root is not valid UTF-8.") from exc
    if top_level != root:
        return {
            "git_available": True,
            "is_repository": False,
            "reason": "repository_root_outside_workspace",
        }
    return {"git_available": True, "is_repository": True, "reason": None}


def _run_git(
    cwd: Path,
    *args: str,
    allow_not_repository: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Git command timed out after {GIT_TIMEOUT_SECONDS} seconds.") from exc
    except OSError as exc:
        raise ValueError(f"Git command failed to start: {exc}") from exc
    if completed.returncode != 0 and not allow_not_repository:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git command exited with code {completed.returncode}: {stderr[:1_000]}")
    return completed


def _parse_status(raw: bytes) -> tuple[list[dict[str, Any]], bool]:
    records = raw.split(b"\0")
    if records and records[-1] == b"":
        records.pop()

    entries: list[dict[str, Any]] = []
    parsed_bytes = 0
    index = 0
    while index < len(records):
        if len(entries) >= MAX_STATUS_ENTRIES:
            return entries, True
        record = records[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("Malformed Git status record.")
        record_bytes = len(record) + 1
        try:
            xy = record[:2].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("Malformed Git status record.") from exc
        original_path: str | None = None
        if "R" in xy or "C" in xy:
            if index + 1 >= len(records):
                raise ValueError("Malformed Git status record: missing rename source.")
            original = records[index + 1]
            record_bytes += len(original) + 1
            index += 1
        if parsed_bytes + record_bytes > MAX_STATUS_BYTES:
            return entries, True
        path = _decode_status_path(record[3:])
        if "R" in xy or "C" in xy:
            if not original:
                raise ValueError("Malformed Git status record: empty rename source.")
            original_path = _decode_status_path(original)
        parsed_bytes += record_bytes
        index_status, worktree_status = xy
        untracked = xy == "??"
        entries.append(
            {
                "path": path,
                "original_path": original_path,
                "index_status": None if index_status in {" ", "?", "!"} else index_status,
                "worktree_status": None if worktree_status in {" ", "?", "!"} else worktree_status,
                "staged": not untracked and index_status not in {" ", "?", "!"},
                "unstaged": not untracked and worktree_status not in {" ", "?", "!"},
                "untracked": untracked,
                "conflicted": xy in _CONFLICT_STATUSES,
            }
        )
        index += 1
    return entries, False


def _decode_status_path(raw: bytes) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Git status path is not valid UTF-8.") from exc
