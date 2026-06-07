from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


HookHandler = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class HookRecord:
    event: str
    hook: str
    status: str
    created_at: str
    error: str | None = None


@dataclass(frozen=True)
class HookRunResult:
    records: list[HookRecord]
    blocking_error: str | None = None


def run_hooks(
    *,
    event: str,
    enabled_hooks: tuple[str, ...],
    blocking_hooks: tuple[str, ...],
    payload: dict[str, Any],
    log_path: Path,
) -> HookRunResult:
    if not enabled_hooks:
        return HookRunResult([])
    records: list[HookRecord] = []
    blocking_error = None
    for hook_name in enabled_hooks:
        handler = BUILTIN_HOOKS.get(hook_name)
        if handler is None:
            record = HookRecord(event=event, hook=hook_name, status="error", created_at=_now(), error="Unknown hook.")
        else:
            try:
                handler(payload)
                record = HookRecord(event=event, hook=hook_name, status="ok", created_at=_now())
            except Exception as exc:  # noqa: BLE001 - hook failures are isolated and logged.
                record = HookRecord(event=event, hook=hook_name, status="error", created_at=_now(), error=str(exc))
        records.append(record)
        if record.status == "error" and hook_name in blocking_hooks and blocking_error is None:
            blocking_error = f"Blocking hook failed: {hook_name}: {record.error}"
    _append_hook_records(log_path, records)
    return HookRunResult(records, blocking_error)


def _audit_hook(payload: dict[str, Any]) -> None:
    return None


def _fail_hook(payload: dict[str, Any]) -> None:
    raise RuntimeError("Hook failed.")


BUILTIN_HOOKS: dict[str, HookHandler] = {
    "audit": _audit_hook,
    "fail": _fail_hook,
}


def _append_hook_records(path: Path, records: list[HookRecord]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
