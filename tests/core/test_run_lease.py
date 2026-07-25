from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent.core import run_lease
from agent.core.run_lease import RunLeaseBusy, RunLeaseError, WorkspaceRunLease, read_workspace_owner


def test_workspace_run_lease_is_exclusive_and_reusable(tmp_path: Path) -> None:
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()

    first = WorkspaceRunLease.acquire(first_workspace, owner={"kind": "web", "job_id": "job_1"})
    try:
        with pytest.raises(RunLeaseBusy, match="already has an active Agent turn"):
            WorkspaceRunLease.acquire(first_workspace, owner={"kind": "cli"})
        other = WorkspaceRunLease.acquire(second_workspace, owner={"kind": "cli"})
        other.release()
    finally:
        first.release()

    again = WorkspaceRunLease.acquire(first_workspace, owner={"kind": "cli"})
    again.release()


def test_workspace_run_lease_context_releases_after_exception(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(RuntimeError, match="boom"):
        with WorkspaceRunLease.acquire(workspace, owner={"kind": "test"}):
            raise RuntimeError("boom")

    WorkspaceRunLease.acquire(workspace, owner={"kind": "retry"}).release()


def test_workspace_owner_is_bounded_redacted_diagnostic_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = "sk-test-secret-123456"

    lease = WorkspaceRunLease.acquire(
        workspace,
        owner={"kind": "web", "session_id": "chat_1", "note": f"token {secret}"},
    )
    try:
        owner = read_workspace_owner(workspace)
        lock_text = json.dumps(owner, ensure_ascii=True, separators=(",", ":"))

        assert owner == {"kind": "web", "session_id": "chat_1", "note": "token [REDACTED]"}
        assert secret not in lock_text
        assert len(lock_text.encode("utf-8")) <= 2048
        assert json.loads(lock_text) == owner
    finally:
        lease.release()

    assert read_workspace_owner(workspace) is None


def test_workspace_run_lease_rejects_oversized_owner(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(RunLeaseError, match="owner diagnostic is too large"):
        WorkspaceRunLease.acquire(workspace, owner={"kind": "test", "note": "x" * 3000})

    WorkspaceRunLease.acquire(workspace, owner={"kind": "retry"}).release()


def test_workspace_run_lease_releases_os_lock_when_owner_write_fails(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = run_lease._write_owner
    calls = 0

    def fail_once(handle, encoded: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RunLeaseError("owner write failed")
        original(handle, encoded)

    monkeypatch.setattr(run_lease, "_write_owner", fail_once)

    with pytest.raises(RunLeaseError, match="owner write failed"):
        WorkspaceRunLease.acquire(workspace, owner={"kind": "first"})
    WorkspaceRunLease.acquire(workspace, owner={"kind": "retry"}).release()


def test_workspace_run_lease_rejects_redirected_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    (workspace / ".agent").mkdir()
    try:
        os.symlink(external, workspace / ".agent" / "chat-jobs", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(RunLeaseError, match="real directory"):
        WorkspaceRunLease.acquire(workspace, owner={"kind": "test"})


def test_workspace_run_lease_is_authoritative_across_processes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    workspace.mkdir()
    source_root = Path(__file__).resolve().parents[2] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source_root), *([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])]
    )
    script = """
import sys
import time
from pathlib import Path
from agent.core.run_lease import WorkspaceRunLease

workspace, ready, stop = map(Path, sys.argv[1:])
lease = WorkspaceRunLease.acquire(workspace, owner={"kind": "child"})
ready.write_text("ready", encoding="utf-8")
try:
    while not stop.exists():
        time.sleep(0.01)
finally:
    lease.release()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(workspace), str(ready), str(stop)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file(), process.communicate(timeout=1.0)

        with pytest.raises(RunLeaseBusy, match="already has an active Agent turn"):
            WorkspaceRunLease.acquire(workspace, owner={"kind": "parent"})

        stop.write_text("stop", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=5.0)
        assert process.returncode == 0, (stdout, stderr)
        WorkspaceRunLease.acquire(workspace, owner={"kind": "parent"}).release()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5.0)
