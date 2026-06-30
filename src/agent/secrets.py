from __future__ import annotations

import os
from pathlib import Path


def load_workspace_secrets(workspace: Path) -> Path | None:
    path = workspace.resolve() / ".agent" / "secrets.env"
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if key and key not in os.environ:
            os.environ[key] = _unquote(value.strip())
    return path


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
