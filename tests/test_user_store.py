from __future__ import annotations

import errno
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import agent._user_store as user_store
from agent._user_store import UserStoreError

_CRASH_FIXTURE = (Path(__file__).parent / "fixtures" / "extension_crash_worker.py").resolve()
_SKILL_FIXTURE = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-v1").resolve()
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z", re.ASCII)
_OWNER = b"agent:test-transaction:v1\n"


def _root(tmp_path) -> Path:
    root = tmp_path / ".agent"
    root.mkdir(parents=True)
    return root


def test_store_lock_is_exclusive_and_released_on_exit(tmp_path) -> None:
    root = _root(tmp_path)

    with user_store.store_lock(root):
        assert (root / user_store.LOCK_FILE_NAME).is_file()

    with user_store.store_lock(root):
        pass


def test_store_lock_times_out_while_another_process_holds_it(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "hold-lock",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--ready",
            str(ready),
        ]
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        monkeypatch.setattr(user_store, "LOCK_TIMEOUT_SECONDS", 0.05)
        with pytest.raises(UserStoreError, match="busy"):
            with user_store.store_lock(home / ".agent"):
                pass
    finally:
        process.terminate()
        process.wait(timeout=5)

    with user_store.store_lock(home / ".agent"):
        pass


def test_store_lock_rejects_a_linked_lock_file(tmp_path) -> None:
    root = _root(tmp_path)
    target = tmp_path / "outside.lock"
    target.write_bytes(b"\0")
    try:
        (root / user_store.LOCK_FILE_NAME).symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(UserStoreError, match="link|reparse"):
        with user_store.store_lock(root):
            pass


def test_atomic_replace_publishes_and_cleans_its_temporary_file(tmp_path) -> None:
    root = _root(tmp_path)
    target = root / "state.json"

    user_store.atomic_replace_json(root, target, {"version": 1, "disabled": []})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1, "disabled": []}
    assert not list(root.glob(f".{target.name}.agent-*"))


def test_atomic_replace_keeps_previous_bytes_when_publish_fails(tmp_path, monkeypatch) -> None:
    root = _root(tmp_path)
    target = root / "state.json"
    user_store.atomic_replace_bytes(root, target, b"original\n")
    real_replace = os.replace

    def failing_replace(source, destination):
        if Path(destination) == target:
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(user_store.os, "replace", failing_replace)

    with pytest.raises(UserStoreError, match="write"):
        user_store.atomic_replace_bytes(root, target, b"replacement\n")

    assert target.read_bytes() == b"original\n"
    assert not list(root.glob(f".{target.name}.agent-*"))


def test_atomic_replace_enforces_the_state_size_limit(tmp_path) -> None:
    root = _root(tmp_path)

    with pytest.raises(UserStoreError, match="too large"):
        user_store.atomic_replace_json(root, root / "state.json", {"blob": "x" * 100}, max_bytes=32)


def test_atomic_replace_rejects_targets_outside_the_store(tmp_path) -> None:
    root = _root(tmp_path)

    with pytest.raises(UserStoreError, match="escapes"):
        user_store.atomic_replace_bytes(root, tmp_path / "outside.json", b"{}\n")


def test_require_store_path_rejects_linked_parents(tmp_path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links are unavailable: {exc}")

    with pytest.raises(UserStoreError, match="link|reparse"):
        user_store.require_store_path(root, root / "linked" / "state.json")


def test_directory_sync_propagates_real_io_failures(tmp_path, monkeypatch) -> None:
    def failing_fsync(_descriptor: int) -> None:
        raise OSError(errno.EIO, "simulated directory sync failure")

    with monkeypatch.context() as patch:
        patch.setattr(user_store.os, "name", "posix")
        patch.setattr(user_store.os, "open", lambda _path, _flags: 42)
        patch.setattr(user_store.os, "fsync", failing_fsync)
        patch.setattr(user_store.os, "close", lambda _descriptor: None)
        with pytest.raises(UserStoreError, match="synchronize"):
            user_store.sync_directory(tmp_path)


@pytest.mark.parametrize(
    ("value", "safe"),
    [
        ("reviewer", True),
        ("a.b-c_1", True),
        ("a" * 64, True),
        ("a" * 65, False),
        ("", False),
        (".hidden", False),
        ("trailing.", False),
        ("trailing ", False),
        ("CON", False),
        ("nul", False),
        ("has/slash", False),
        (None, False),
    ],
)
def test_safe_store_name_rules(value, safe) -> None:
    assert user_store.is_safe_store_name(value, max_length=64, pattern=_NAME_PATTERN) is safe


def test_allocate_transaction_writes_an_owner_marker(tmp_path) -> None:
    root = _root(tmp_path)

    tx = user_store.allocate_transaction(root, prefix="test", owner_marker=_OWNER)

    assert tx.parent.name == user_store.TRANSACTIONS_DIR_NAME
    assert (tx / user_store.OWNER_MARKER_NAME).read_bytes() == _OWNER
    assert user_store.transaction_name_pattern("test").fullmatch(tx.name) is not None
    assert user_store.owned_transactions(root, prefix="test") == (tx,)
    assert user_store.owned_transactions(root, prefix="other") == ()


def test_allocate_transaction_cleans_up_when_the_owner_write_fails(tmp_path, monkeypatch) -> None:
    root = _root(tmp_path)
    real_write_new_file = user_store.write_new_file

    def failing_owner(path: Path, data: bytes) -> None:
        if path.name == user_store.OWNER_MARKER_NAME:
            raise UserStoreError("injected owner failure")
        real_write_new_file(path, data)

    monkeypatch.setattr(user_store, "write_new_file", failing_owner)

    with pytest.raises(UserStoreError, match="injected owner failure"):
        user_store.allocate_transaction(root, prefix="test", owner_marker=_OWNER)

    assert user_store.owned_transactions(root, prefix="test") == ()


def test_transaction_entries_require_a_trustworthy_owner_marker(tmp_path) -> None:
    root = _root(tmp_path)
    tx = user_store.allocate_transaction(root, prefix="test", owner_marker=_OWNER)
    user_store.write_record(root, tx, {"version": 1, "module": "test", "operation": "set", "phase": "prepared"})

    entries = user_store.transaction_entries(
        tx,
        prefix="test",
        allowed_names=frozenset({"candidate"}),
        owner_marker=_OWNER,
        require_owner=True,
    )
    assert {path.name for path in entries} == {user_store.OWNER_MARKER_NAME, "record.json"}

    (tx / user_store.OWNER_MARKER_NAME).write_bytes(b"someone-else\n")
    with pytest.raises(UserStoreError, match="ownership marker"):
        user_store.transaction_entries(
            tx,
            prefix="test",
            allowed_names=frozenset({"candidate"}),
            owner_marker=_OWNER,
            require_owner=True,
        )


def test_transaction_entries_reject_unknown_entries_and_foreign_names(tmp_path) -> None:
    root = _root(tmp_path)
    tx = user_store.allocate_transaction(root, prefix="test", owner_marker=_OWNER)
    (tx / "stray.txt").write_text("x", encoding="utf-8")

    with pytest.raises(UserStoreError, match="unknown or unsafe"):
        user_store.transaction_entries(
            tx,
            prefix="test",
            allowed_names=frozenset({"candidate"}),
            owner_marker=_OWNER,
            require_owner=False,
        )

    foreign = tx.parent / f"other-{'a' * 32}"
    foreign.mkdir()
    with pytest.raises(UserStoreError, match="not trustworthy"):
        user_store.transaction_entries(
            foreign,
            prefix="test",
            allowed_names=frozenset({"candidate"}),
            owner_marker=_OWNER,
            require_owner=False,
        )


def test_read_record_validates_the_shared_envelope(tmp_path) -> None:
    root = _root(tmp_path)
    tx = user_store.allocate_transaction(root, prefix="test", owner_marker=_OWNER)
    fields = frozenset({"version", "module", "operation", "phase"})
    operations = frozenset({"set"})
    user_store.write_record(root, tx, {"version": 1, "module": "test", "operation": "set", "phase": "prepared"})

    assert user_store.read_record(tx, module="test", fields=fields, operations=operations)["phase"] == "prepared"

    user_store.write_record(root, tx, {"version": 1, "module": "test", "operation": "set"})
    with pytest.raises(UserStoreError, match="unknown or missing fields"):
        user_store.read_record(tx, module="test", fields=fields, operations=operations)

    user_store.write_record(root, tx, {"version": 2, "module": "test", "operation": "set", "phase": "prepared"})
    with pytest.raises(UserStoreError, match="version or module"):
        user_store.read_record(tx, module="test", fields=fields, operations=operations)

    user_store.write_record(root, tx, {"version": 1, "module": "test", "operation": "drop", "phase": "prepared"})
    with pytest.raises(UserStoreError, match="operation or phase"):
        user_store.read_record(tx, module="test", fields=fields, operations=operations)


def test_remove_tree_deletes_nested_content_without_following_links(tmp_path) -> None:
    root = _root(tmp_path)
    target = root / "tree"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "file.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    linked = False
    try:
        (target / "link").symlink_to(outside, target_is_directory=True)
        linked = True
    except OSError:
        pass

    user_store.remove_tree(target, message="Could not remove the tree.")

    assert not target.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert linked or True


def _crash_worker(mode: str, *, workspace: Path, home: Path, crash_at: str, extra: list[str] | None = None) -> int:
    process = subprocess.run(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            mode,
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--crash-at",
            crash_at,
            *(extra or []),
        ],
        capture_output=True,
    )
    return process.returncode


@pytest.mark.parametrize("crash_at", ["prepared", "target", "state", "committed"])
def test_skill_install_crash_leaves_only_old_or_new_state(tmp_path, crash_at) -> None:
    from agent.core.skills import SkillStore, discover_skills

    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    assert _crash_worker(
        "crash-skill-install",
        workspace=workspace,
        home=home,
        crash_at=crash_at,
        extra=["--source", str(_SKILL_FIXTURE)],
    ) == 91

    store = SkillStore(workspace, home=home)
    names = {item.name: item for item in store.inventory()}
    installed = home / ".agent" / "skills" / "reviewer"
    if "reviewer" in names and names["reviewer"].source == "user":
        assert installed.is_dir()
        assert (installed / "SKILL.md").is_file()
        assert discover_skills(workspace, home=home)["reviewer"].source == "user"
    else:
        assert not installed.exists()
    assert not list((home / ".agent" / user_store.TRANSACTIONS_DIR_NAME).glob("skill-*")) or store.inventory()
