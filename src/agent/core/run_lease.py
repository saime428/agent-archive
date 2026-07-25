from __future__ import annotations

import errno
import json
import os
import threading
from pathlib import Path
from typing import Any

from agent import _user_store
from agent.core.redaction import redact_value


_OWNER_MAX_BYTES = 2048
_PROCESS_GUARD = threading.Lock()
_PROCESS_HELD: set[str] = set()


class RunLeaseError(ValueError):
    pass


class RunLeaseBusy(RunLeaseError):
    pass


class WorkspaceRunLease:
    def __init__(self, lock_path: Path, handle, process_key: str) -> None:
        self.lock_path = lock_path
        self._handle = handle
        self._process_key = process_key
        self._released = False

    @classmethod
    def acquire(cls, workspace: Path, *, owner: dict[str, Any]) -> "WorkspaceRunLease":
        encoded_owner = _encode_owner(owner)
        root = _ensure_storage_root(workspace)
        lock_path = root / "workspace.lock"
        process_key = _user_store.comparison_path(lock_path)
        with _PROCESS_GUARD:
            if process_key in _PROCESS_HELD:
                raise RunLeaseBusy("Workspace already has an active Agent turn.")
            _PROCESS_HELD.add(process_key)

        handle = None
        acquired = False
        completed = False
        try:
            if _user_store.lexists(lock_path):
                _user_store.require_plain_file(
                    lock_path,
                    message="Workspace run lock must be a regular file, not a link or reparse point.",
                )
            handle = lock_path.open("a+b", buffering=0)
            _user_store.require_plain_file(
                lock_path,
                message="Workspace run lock must remain a regular file.",
            )
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                _lock_file(handle)
            except OSError as exc:
                if _lock_would_block(exc):
                    raise RunLeaseBusy("Workspace already has an active Agent turn.") from exc
                raise RunLeaseError("Could not acquire the workspace run lock.") from exc
            acquired = True
            _write_owner(handle, encoded_owner)
            lease = cls(lock_path, handle, process_key)
            completed = True
            return lease
        except _user_store.UserStoreError as exc:
            raise RunLeaseError(exc.message) from exc
        except OSError as exc:
            raise RunLeaseError("Could not open the workspace run lock.") from exc
        finally:
            if not completed:
                if acquired and handle is not None:
                    try:
                        handle.seek(0)
                        _unlock_file(handle)
                    except OSError:
                        pass
                if handle is not None:
                    handle.close()
                with _PROCESS_GUARD:
                    _PROCESS_HELD.discard(process_key)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            try:
                _write_owner(self._handle, b"")
            finally:
                self._handle.seek(0)
                _unlock_file(self._handle)
        finally:
            self._handle.close()
            with _PROCESS_GUARD:
                _PROCESS_HELD.discard(self._process_key)

    def __enter__(self) -> "WorkspaceRunLease":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def read_workspace_owner(workspace: Path) -> dict[str, Any] | None:
    root = _existing_storage_root(workspace)
    if root is None:
        return None
    lock_path = root / "workspace.lock"
    if not _user_store.lexists(lock_path):
        return None
    try:
        _user_store.require_plain_file(
            lock_path,
            message="Workspace run lock must be a regular file, not a link or reparse point.",
        )
        with lock_path.open("rb") as handle:
            handle.seek(1)
            raw = handle.read()
    except _user_store.UserStoreError as exc:
        raise RunLeaseError(exc.message) from exc
    except OSError as exc:
        raise RunLeaseError("Could not read the workspace run owner.") from exc
    if not raw:
        return None
    try:
        owner = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RunLeaseError("Workspace run owner diagnostic is invalid.") from exc
    if not isinstance(owner, dict):
        raise RunLeaseError("Workspace run owner diagnostic must be an object.")
    return owner


def _encode_owner(owner: dict[str, Any]) -> bytes:
    if not isinstance(owner, dict):
        raise RunLeaseError("Workspace run owner diagnostic must be an object.")
    try:
        encoded = json.dumps(
            redact_value(owner).value,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RunLeaseError("Workspace run owner diagnostic must be JSON serializable.") from exc
    if len(encoded) > _OWNER_MAX_BYTES:
        raise RunLeaseError("Workspace run owner diagnostic is too large.")
    return encoded


def _ensure_storage_root(workspace: Path) -> Path:
    root = workspace.resolve()
    if not root.is_dir():
        raise RunLeaseError(f"Workspace is not a directory: {root}")
    agent_root = root / ".agent"
    storage_root = agent_root / "chat-jobs"
    try:
        _ensure_real_directory(agent_root, parent=root)
        _ensure_real_directory(storage_root, parent=agent_root)
    except _user_store.UserStoreError as exc:
        raise RunLeaseError(exc.message) from exc
    return storage_root


def _existing_storage_root(workspace: Path) -> Path | None:
    root = workspace.resolve()
    agent_root = root / ".agent"
    storage_root = agent_root / "chat-jobs"
    if not _user_store.lexists(agent_root):
        return None
    try:
        _user_store.require_real_directory(agent_root, message="Agent storage must be a real directory.")
        if not _user_store.lexists(storage_root):
            return None
        _user_store.require_real_directory(storage_root, message="Chat job storage must be a real directory.")
    except _user_store.UserStoreError as exc:
        raise RunLeaseError(exc.message) from exc
    return storage_root


def _ensure_real_directory(path: Path, *, parent: Path) -> None:
    if _user_store.lexists(path):
        _user_store.require_real_directory(path, message=f"{path.name} storage must be a real directory.")
        return
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _user_store.require_real_directory(path, message=f"{path.name} storage must be a real directory.")
        return
    except OSError as exc:
        raise _user_store.UserStoreError(f"Could not create {path.name} storage.") from exc
    _user_store.sync_directory(parent)


def _write_owner(handle, encoded: bytes) -> None:
    try:
        handle.seek(1)
        if encoded:
            handle.write(encoded)
        handle.truncate(1 + len(encoded))
        handle.flush()
        os.fsync(handle.fileno())
    except OSError as exc:
        raise RunLeaseError("Could not write the workspace run owner diagnostic.") from exc


def _lock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_would_block(exc: OSError) -> bool:
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
