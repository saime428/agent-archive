from __future__ import annotations

import os
from pathlib import Path

from agent.core.actions import ErrorCode

PROTECTED_WRITE_PARTS = {".git", "__pycache__", ".pytest_cache"}


class SandboxError(ValueError):
    def __init__(self, code: ErrorCode, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class WorkspaceSandbox:
    def __init__(self, root: Path, *, allow_external_read: bool = False, allow_external_write: bool = False) -> None:
        self.root = root.resolve()
        self.protected_runs_root = (self.root / ".agent" / "runs").resolve()
        self.allow_external_read = allow_external_read
        self.allow_external_write = allow_external_write

    def resolve_read_path(self, path: str, *, allow_external: bool = True) -> Path:
        requested = Path(path).expanduser()
        explicit_external = requested.is_absolute() or path.startswith(("~", "~/", "~\\"))
        candidate = requested if requested.is_absolute() else self.root / requested
        resolved = candidate.resolve()
        if _is_protected_read_path(resolved, self.protected_runs_root):
            raise SandboxError(
                ErrorCode.SANDBOX_VIOLATION,
                "Path targets protected internal state.",
                {"path": path},
            )
        if not _is_within(resolved, self.root):
            if self.allow_external_read and allow_external and explicit_external:
                return resolved
            raise SandboxError(
                ErrorCode.SANDBOX_VIOLATION,
                "Path resolves outside the workspace.",
                {"path": path},
            )
        return resolved

    def resolve_write_path(self, path: str, *, create_parents: bool = False) -> Path:
        requested = Path(path)
        candidate = requested if requested.is_absolute() else self.root / requested
        nearest_parent = _nearest_existing_parent(candidate)
        resolved_parent = nearest_parent.resolve()
        if not _is_within(resolved_parent, self.root):
            if not self.allow_external_write or not requested.is_absolute():
                raise SandboxError(
                    ErrorCode.SANDBOX_VIOLATION,
                    "Path resolves outside the workspace.",
                    {"path": path},
                )

        resolved = candidate.resolve(strict=False)
        if not _is_within(resolved, self.root):
            if not self.allow_external_write or not requested.is_absolute():
                raise SandboxError(
                    ErrorCode.SANDBOX_VIOLATION,
                    "Path resolves outside the workspace.",
                    {"path": path},
                )
            if not create_parents and not resolved.parent.exists():
                raise SandboxError(
                    ErrorCode.TOOL_FAILED,
                    "Parent directory does not exist.",
                    {"path": path, "parent": str(resolved.parent)},
                )
            return resolved
        if _has_protected_write_part(resolved, self.root):
            raise SandboxError(
                ErrorCode.SANDBOX_VIOLATION,
                "Path targets protected internal state.",
                {"path": path},
            )
        if not create_parents and not resolved.parent.exists():
            raise SandboxError(
                ErrorCode.TOOL_FAILED,
                "Parent directory does not exist.",
                {"path": path, "parent": str(resolved.parent)},
            )
        return resolved


def _is_within(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root))
    try:
        return os.path.commonpath([path_text, root_text]) == root_text
    except ValueError:
        return False


def _is_protected_read_path(path: Path, protected_runs_root: Path) -> bool:
    if _is_within(path, protected_runs_root):
        return True
    parts = tuple(os.path.normcase(part) for part in path.parts)
    return any(parts[index] == ".agent" and parts[index + 1] == "secrets.env" for index in range(len(parts) - 1))


def _nearest_existing_parent(path: Path) -> Path:
    current = path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _has_protected_write_part(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True
    if relative_parts and relative_parts[0] == ".agent":
        return True
    return any(part in PROTECTED_WRITE_PARTS for part in relative_parts)
