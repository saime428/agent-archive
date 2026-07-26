from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.web import git as web_git


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    return completed


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--quiet")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "core.autocrlf", "false")


def _commit_all(path: Path, message: str = "base") -> None:
    _git(path, "add", ".")
    _git(path, "commit", "--quiet", "-m", message)


def test_git_status_structures_staged_unstaged_untracked_and_rename(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    _init_repo(workspace)
    for name in ("both.txt", "unstaged.txt", "rename old.txt"):
        (workspace / name).write_text("base\n", encoding="utf-8")
    _commit_all(workspace)

    (workspace / "both.txt").write_text("staged\n", encoding="utf-8")
    _git(workspace, "add", "both.txt")
    (workspace / "both.txt").write_text("worktree\n", encoding="utf-8")
    (workspace / "unstaged.txt").write_text("changed\n", encoding="utf-8")
    (workspace / "untracked ü space.txt").write_text("new\n", encoding="utf-8")
    _git(workspace, "mv", "rename old.txt", "rename new.txt")

    payload = web_git.build_git_status_payload(workspace)
    entries = {entry["path"]: entry for entry in payload["entries"]}

    assert payload["git_available"] is True
    assert payload["is_repository"] is True
    assert payload["reason"] is None
    assert payload["truncated"] is False
    assert entries["both.txt"] == {
        "path": "both.txt",
        "original_path": None,
        "index_status": "M",
        "worktree_status": "M",
        "staged": True,
        "unstaged": True,
        "untracked": False,
        "conflicted": False,
    }
    assert entries["unstaged.txt"]["staged"] is False
    assert entries["unstaged.txt"]["unstaged"] is True
    assert entries["untracked ü space.txt"]["untracked"] is True
    assert entries["rename new.txt"]["index_status"] == "R"
    assert entries["rename new.txt"]["original_path"] == "rename old.txt"


def test_git_status_reports_clean_unborn_non_repo_and_parent_repo(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    _init_repo(clean)
    (clean / "tracked.txt").write_text("base\n", encoding="utf-8")
    _commit_all(clean)
    assert web_git.build_git_status_payload(clean)["entries"] == []

    unborn = tmp_path / "unborn"
    _init_repo(unborn)
    (unborn / "new.txt").write_text("new\n", encoding="utf-8")
    unborn_payload = web_git.build_git_status_payload(unborn)
    assert unborn_payload["is_repository"] is True
    assert unborn_payload["entries"][0]["untracked"] is True

    plain = tmp_path / "plain"
    plain.mkdir()
    plain_payload = web_git.build_git_status_payload(plain)
    assert plain_payload["is_repository"] is False
    assert plain_payload["reason"] == "not_repository"

    parent = tmp_path / "parent"
    _init_repo(parent)
    child = parent / "child"
    child.mkdir()
    child_payload = web_git.build_git_status_payload(child)
    assert child_payload["is_repository"] is False
    assert child_payload["reason"] == "repository_root_outside_workspace"


def test_git_status_reports_unavailable_and_rejects_abnormal_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_git.shutil, "which", lambda _name: None)
    unavailable = web_git.build_git_status_payload(tmp_path)
    assert unavailable["reason"] == "git_unavailable"
    assert unavailable["git_available"] is False

    monkeypatch.setattr(web_git.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        web_git,
        "_run_git",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=128,
            stdout=b"",
            stderr=b"fatal: unsafe repository",
        ),
    )
    with pytest.raises(ValueError, match="unsafe repository"):
        web_git.build_git_status_payload(tmp_path)


def test_git_status_marks_conflicts_and_bounds_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "repo"
    _init_repo(workspace)
    target = workspace / "conflict.txt"
    target.write_text("base\n", encoding="utf-8")
    _commit_all(workspace)
    default_branch = _git(workspace, "branch", "--show-current").stdout.decode().strip()
    _git(workspace, "checkout", "-q", "-b", "other")
    target.write_text("other\n", encoding="utf-8")
    _commit_all(workspace, "other")
    _git(workspace, "checkout", "-q", default_branch)
    target.write_text("main\n", encoding="utf-8")
    _commit_all(workspace, "main")
    assert _git(workspace, "merge", "other", check=False).returncode != 0

    conflict = web_git.build_git_status_payload(workspace)["entries"][0]
    assert conflict["path"] == "conflict.txt"
    assert conflict["conflicted"] is True

    (workspace / "extra.txt").write_text("extra\n", encoding="utf-8")
    monkeypatch.setattr(web_git, "MAX_STATUS_ENTRIES", 1)
    bounded = web_git.build_git_status_payload(workspace)
    assert len(bounded["entries"]) == 1
    assert bounded["entry_count"] == 1
    assert bounded["truncated"] is True


def test_git_status_parser_rejects_malformed_and_invalid_utf8() -> None:
    with pytest.raises(ValueError, match="Malformed Git status record"):
        web_git._parse_status(b"broken\0")
    with pytest.raises(ValueError, match="UTF-8"):
        web_git._parse_status(b"?? bad-\xff\0")


def test_git_diff_separates_staged_and_unstaged_and_handles_deleted_binary(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    _init_repo(workspace)
    target = workspace / "notes.txt"
    deleted = workspace / "deleted.txt"
    binary = workspace / "binary.bin"
    target.write_text("base\n", encoding="utf-8")
    deleted.write_text("remove me\n", encoding="utf-8")
    binary.write_bytes(b"old\0bytes")
    _commit_all(workspace)

    target.write_text("staged\n", encoding="utf-8")
    _git(workspace, "add", "notes.txt")
    target.write_text("worktree\n", encoding="utf-8")
    deleted.unlink()
    binary.write_bytes(b"new\0bytes")

    staged = web_git.build_git_diff_payload(workspace, "notes.txt", "staged")
    unstaged = web_git.build_git_diff_payload(workspace, "notes.txt", "unstaged")
    deleted_payload = web_git.build_git_diff_payload(workspace, "deleted.txt", "unstaged")
    binary_payload = web_git.build_git_diff_payload(workspace, "binary.bin", "unstaged")

    assert staged["path"] == "notes.txt"
    assert staged["area"] == "staged"
    assert "+staged" in staged["diff"]
    assert "worktree" not in staged["diff"]
    assert unstaged["area"] == "unstaged"
    assert "-staged" in unstaged["diff"]
    assert "+worktree" in unstaged["diff"]
    assert "deleted file mode" in deleted_payload["diff"]
    assert "Binary files" in binary_payload["diff"]


def test_git_diff_rejects_invalid_area_and_path_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    _init_repo(workspace)

    with pytest.raises(ValueError, match="area must be staged or unstaged"):
        web_git.build_git_diff_payload(workspace, "file.txt", "head")
    with pytest.raises(ValueError, match="SANDBOX_VIOLATION"):
        web_git.build_git_diff_payload(workspace, "../outside.txt", "unstaged")
    with pytest.raises(ValueError, match="relative to the workspace"):
        web_git.build_git_diff_payload(workspace, str((workspace / "file.txt").resolve()), "unstaged")
