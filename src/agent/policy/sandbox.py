from __future__ import annotations

import os
from pathlib import Path

from agent.core.actions import ErrorCode


class SandboxError(ValueError):
    def __init__(self, code: ErrorCode, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class WorkspaceSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.protected_runs_root = (self.root / ".agent" / "runs").resolve()

    def resolve_read_path(self, path: str) -> Path:
        requested = Path(path)
        candidate = requested if requested.is_absolute() else self.root / requested
        resolved = candidate.resolve()
        if not _is_within(resolved, self.root):
            raise SandboxError(
                ErrorCode.SANDBOX_VIOLATION,
                "Path resolves outside the workspace.",
                {"path": path},
            )
        if _is_within(resolved, self.protected_runs_root):
            raise SandboxError(
                ErrorCode.SANDBOX_VIOLATION,
                "Path targets protected internal run state.",
                {"path": path},
            )
        return resolved


def _is_within(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root))
    try:
        return os.path.commonpath([path_text, root_text]) == root_text
    except ValueError:
        return False
