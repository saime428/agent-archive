"""Shared primitives for user-level extension stores under ``~/.agent``.

MCP configuration and user Skills both publish state into the same user store,
so the lock, canonical path checks, atomic publish and transaction record
plumbing live here. Rollback, authoritative-target validation and state
interpretation stay in the owning module.
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.05
TRANSACTIONS_DIR_NAME = ".extension-transactions"
LOCK_FILE_NAME = ".extension.lock"
OWNER_MARKER_NAME = ".owner"

_TEMP_NAME_PATTERN = re.compile(r"[0-9a-f]{32}\.tmp\Z", re.ASCII)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class UserStoreError(RuntimeError):
    """Raised by shared store primitives; owning modules map it to their own error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def is_link_or_reparse(path: Path) -> bool:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return stat.S_ISLNK(details.st_mode) or bool(getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def has_windows_device_prefix(path: Path) -> bool:
    if os.name != "nt":
        return False
    value = str(path).replace("/", "\\")
    return value.startswith("\\\\?\\") or value.startswith("\\\\.\\")


def comparison_path(path: Path) -> str:
    value = os.path.normcase(os.path.normpath(str(path)))
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\unc\\"):
        return f"\\\\{value[8:]}"
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def is_within(path: Path, root: Path) -> bool:
    path_text = comparison_path(path)
    root_text = comparison_path(root)
    try:
        if os.path.commonpath([path_text, root_text]) == root_text:
            return True
    except ValueError:
        pass
    for candidate in (path, *path.parents):
        try:
            if candidate.samefile(root):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def require_real_directory(path: Path, *, message: str) -> None:
    if is_link_or_reparse(path) or not path.is_dir():
        raise UserStoreError(message)


def require_plain_file(path: Path, *, message: str) -> None:
    if is_link_or_reparse(path) or not path.is_file():
        raise UserStoreError(message)


def require_store_path(root: Path, path: Path) -> None:
    if not is_within(path.parent, root) or has_windows_device_prefix(path):
        raise UserStoreError("Extension path escapes its storage root.")
    current = root
    relative = path.relative_to(root)
    for part in relative.parts[:-1]:
        current /= part
        if lexists(current) and is_link_or_reparse(current):
            raise UserStoreError("Extension path uses a link or reparse point.")


def is_safe_store_name(value: Any, *, max_length: int, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= max_length
        and pattern.fullmatch(value) is not None
        and value.upper() not in _WINDOWS_RESERVED_NAMES
        and value == value.strip()
        and not value.endswith(".")
    )


def is_owned_temp_name(name: str, target_name: str) -> bool:
    prefix = f".{target_name}.agent-"
    return name.startswith(prefix) and _TEMP_NAME_PATTERN.fullmatch(name[len(prefix) :]) is not None


@contextmanager
def store_lock(root: Path) -> Iterator[None]:
    lock_path = root / LOCK_FILE_NAME
    if lexists(lock_path):
        require_plain_file(lock_path, message="Extension lock must be a regular file, not a link or reparse point.")
    try:
        handle = lock_path.open("a+b", buffering=0)
    except OSError as exc:
        raise UserStoreError("Could not open the extension lock.") from exc
    acquired = False
    try:
        require_plain_file(lock_path, message="Extension lock must remain a regular file.")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            os.fsync(handle.fileno())
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            handle.seek(0)
            try:
                _lock_file(handle)
                acquired = True
                break
            except OSError as exc:
                if not _lock_would_block(exc):
                    raise UserStoreError("Could not acquire the extension lock.") from exc
                if time.monotonic() >= deadline:
                    raise UserStoreError("Extension storage is busy.") from exc
                time.sleep(min(LOCK_RETRY_SECONDS, max(0.0, deadline - time.monotonic())))
        require_plain_file(lock_path, message="Extension lock must remain a regular file.")
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                _unlock_file(handle)
            except OSError:
                pass
        handle.close()


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


def atomic_replace_json(root: Path, target: Path, value: Any, *, max_bytes: int | None = None) -> None:
    encoded = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if json.loads(encoded) != value:
        raise UserStoreError("Could not verify serialized extension state.")
    if max_bytes is not None and len(encoded) > max_bytes:
        raise UserStoreError("Extension state is too large.")
    atomic_replace_bytes(root, target, encoded)


def atomic_replace_bytes(root: Path, target: Path, data: bytes) -> None:
    require_store_path(root, target)
    require_real_directory(target.parent, message="Extension target parent must be a real directory.")
    if lexists(target):
        require_plain_file(target, message="Extension target must be a regular file.")
    descriptor = -1
    temp_path: Path | None = None
    try:
        temp_path = target.parent / f".{target.name}.agent-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        require_plain_file(temp_path, message="Extension temporary file must be a regular file.")
        if lexists(target):
            require_plain_file(target, message="Extension target must remain a regular file.")
        os.replace(temp_path, target)
        temp_path = None
        sync_directory(target.parent)
    except UserStoreError:
        raise
    except OSError as exc:
        raise UserStoreError("Could not write extension state.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def write_new_file(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise UserStoreError("Could not write the extension transaction candidate.") from exc
    require_plain_file(path, message="Extension transaction candidate must be a regular file.")


def sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if _directory_sync_is_unsupported(exc):
            return
        raise UserStoreError("Could not open the extension directory for synchronization.") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if not _directory_sync_is_unsupported(exc):
            raise UserStoreError("Could not synchronize the extension directory.") from exc
    finally:
        os.close(descriptor)


def _directory_sync_is_unsupported(exc: OSError) -> bool:
    return exc.errno in {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }


def make_directory(path: Path, *, parent: Path | None, message: str) -> Path:
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise UserStoreError(message) from exc
    if parent is not None:
        sync_directory(parent)
    return path


def transactions_root(root: Path, *, create: bool) -> Path | None:
    transactions = root / TRANSACTIONS_DIR_NAME
    if lexists(transactions):
        require_real_directory(transactions, message="Extension transaction storage must be a real directory.")
        return transactions
    if not create:
        return None
    return make_directory(
        transactions,
        parent=root,
        message="Could not create the extension transaction storage.",
    )


def owned_transactions(root: Path, *, prefix: str) -> tuple[Path, ...]:
    transactions = transactions_root(root, create=False)
    if transactions is None:
        return ()
    try:
        return tuple(path for path in transactions.iterdir() if path.name.startswith(f"{prefix}-"))
    except OSError as exc:
        raise UserStoreError("Could not enumerate extension transactions.") from exc


def allocate_transaction(root: Path, *, prefix: str, owner_marker: bytes) -> Path:
    transactions = transactions_root(root, create=True)
    assert transactions is not None
    tx = transactions / f"{prefix}-{uuid.uuid4().hex}"
    make_directory(tx, parent=None, message="Could not create the extension transaction directory.")
    try:
        write_new_file(tx / OWNER_MARKER_NAME, owner_marker)
        sync_directory(tx)
        sync_directory(transactions)
    except BaseException:
        # The directory was just created here, so this call owns its cleanup.
        _discard_new_transaction(tx)
        raise
    return tx


def _discard_new_transaction(tx: Path) -> None:
    try:
        for path in tx.iterdir():
            path.unlink()
        tx.rmdir()
    except OSError:
        pass


def transaction_name_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(prefix)}-[0-9a-f]{{32}}\Z", re.ASCII)


def transaction_entries(
    tx: Path,
    *,
    prefix: str,
    allowed_names: frozenset[str],
    owner_marker: bytes,
    require_owner: bool,
) -> tuple[Path, ...]:
    require_real_directory(tx, message="Extension transaction must be a real directory.")
    if transaction_name_pattern(prefix).fullmatch(tx.name) is None:
        raise UserStoreError("Extension transaction name is not trustworthy.")
    allowed = {OWNER_MARKER_NAME, "record.json", *allowed_names}
    try:
        entries = tuple(tx.iterdir())
    except OSError as exc:
        raise UserStoreError("Could not enumerate extension transaction files.") from exc
    for path in entries:
        known = path.name in allowed or is_owned_temp_name(path.name, "record.json")
        if not known or is_link_or_reparse(path):
            raise UserStoreError("Extension transaction contains an unknown or unsafe entry.")
        if path.name in allowed_names and path.is_dir():
            continue
        if not path.is_file():
            raise UserStoreError("Extension transaction contains an unknown or unsafe entry.")
    if require_owner:
        owner = tx / OWNER_MARKER_NAME
        if not lexists(owner):
            raise UserStoreError("Unprepared extension transaction has no trustworthy ownership marker.")
        require_plain_file(owner, message="Extension transaction ownership marker must be a regular file.")
        try:
            owned = owner.stat().st_size == len(owner_marker) and owner.read_bytes() == owner_marker
        except OSError as exc:
            raise UserStoreError("Could not read the extension transaction ownership marker.") from exc
        if not owned:
            raise UserStoreError("Extension transaction has no trustworthy ownership marker.")
    return entries


def read_record(
    tx: Path,
    *,
    module: str,
    fields: frozenset[str],
    operations: frozenset[str],
) -> dict[str, Any]:
    path = tx / "record.json"
    require_plain_file(path, message="Extension transaction record must be a regular file.")
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserStoreError("Could not parse the extension transaction record.") from exc
    if not isinstance(values, dict) or set(values) != fields:
        raise UserStoreError("Extension transaction record has unknown or missing fields.")
    if type(values.get("version")) is not int or values.get("version") != 1 or values.get("module") != module:
        raise UserStoreError("Extension transaction record version or module is invalid.")
    if values.get("operation") not in operations or values.get("phase") not in {"prepared", "committed"}:
        raise UserStoreError("Extension transaction record operation or phase is invalid.")
    return values


def write_record(root: Path, tx: Path, record: dict[str, Any]) -> None:
    atomic_replace_json(root, tx / "record.json", record)


def remove_tree(path: Path, *, message: str) -> None:
    """Delete a validated store-owned directory tree without following links."""
    stack = [path]
    directories: list[Path] = []
    while stack:
        current = stack.pop()
        directories.append(current)
        try:
            entries = tuple(current.iterdir())
        except OSError as exc:
            raise UserStoreError(message) from exc
        for entry in entries:
            if is_link_or_reparse(entry) or not entry.is_dir():
                try:
                    entry.unlink()
                except OSError as exc:
                    raise UserStoreError(message) from exc
            else:
                stack.append(entry)
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError as exc:
            raise UserStoreError(message) from exc


__all__ = [
    "LOCK_FILE_NAME",
    "OWNER_MARKER_NAME",
    "TRANSACTIONS_DIR_NAME",
    "UserStoreError",
    "allocate_transaction",
    "atomic_replace_bytes",
    "atomic_replace_json",
    "comparison_path",
    "has_windows_device_prefix",
    "is_owned_temp_name",
    "is_safe_store_name",
    "is_within",
    "is_link_or_reparse",
    "lexists",
    "make_directory",
    "owned_transactions",
    "read_record",
    "remove_tree",
    "require_plain_file",
    "require_real_directory",
    "require_store_path",
    "store_lock",
    "sync_directory",
    "transaction_entries",
    "transaction_name_pattern",
    "transactions_root",
    "write_new_file",
    "write_record",
]
