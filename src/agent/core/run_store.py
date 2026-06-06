from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_dir: Path
    summary_path: Path
    tool_calls_path: Path
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ToolCallRecord:
    line_number: int
    valid: bool
    raw: str
    data: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    run_dir: Path
    summary: str
    tool_calls: list[ToolCallRecord]
    snapshots: list[dict[str, str]]


class RunStoreError(ValueError):
    pass


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runs_root = (self.root / ".agent" / "runs").resolve()

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        if limit < 1:
            return []
        if not self.runs_root.exists():
            return []

        records: list[RunRecord] = []
        for run_dir in self.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            resolved = run_dir.resolve()
            if not _is_within(resolved, self.runs_root):
                continue
            stat = resolved.stat()
            records.append(
                RunRecord(
                    run_id=run_dir.name,
                    run_dir=resolved,
                    summary_path=resolved / "summary.md",
                    tool_calls_path=resolved / "tool_calls.jsonl",
                    created_at=_datetime_from_timestamp(stat.st_ctime),
                    updated_at=_datetime_from_timestamp(stat.st_mtime),
                )
            )

        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records[:limit]

    def show_run(self, run_id: str) -> RunDetail:
        self._validate_run_id(run_id)
        run_dir = (self.runs_root / run_id).resolve()
        if not _is_within(run_dir, self.runs_root):
            raise RunStoreError("Run id resolves outside run storage.")
        if not run_dir.is_dir():
            raise RunStoreError(f"Run not found: {run_id}")

        summary_path = run_dir / "summary.md"
        tool_calls_path = run_dir / "tool_calls.jsonl"
        if not summary_path.is_file():
            raise RunStoreError(f"Run summary missing: {run_id}")

        summary = summary_path.read_text(encoding="utf-8", errors="replace")
        tool_calls = _read_tool_calls(tool_calls_path)
        return RunDetail(
            run_id=run_id,
            run_dir=run_dir,
            summary=summary,
            tool_calls=tool_calls,
            snapshots=_extract_snapshots(tool_calls),
        )

    def _validate_run_id(self, run_id: str) -> None:
        candidate = Path(run_id)
        if (
            not run_id
            or run_id in {".", ".."}
            or candidate.is_absolute()
            or "/" in run_id
            or "\\" in run_id
            or ".." in candidate.parts
        ):
            raise RunStoreError("Invalid run id.")


def _read_tool_calls(path: Path) -> list[ToolCallRecord]:
    if not path.exists():
        return []

    records: list[ToolCallRecord] = []
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            records.append(
                ToolCallRecord(
                    line_number=index,
                    valid=False,
                    raw=line,
                    data=None,
                    error=f"Line {index} is not valid JSON: {exc.msg}",
                )
            )
            continue
        records.append(
            ToolCallRecord(
                line_number=index,
                valid=True,
                raw=line,
                data=data if isinstance(data, dict) else {"value": data},
                error=None,
            )
        )
    return records


def _extract_snapshots(tool_calls: list[ToolCallRecord]) -> list[dict[str, str]]:
    snapshots: list[dict[str, str]] = []
    for record in tool_calls:
        if not record.valid or not record.data:
            continue
        observation = record.data.get("observation")
        if not isinstance(observation, dict):
            continue
        data = observation.get("data")
        if not isinstance(data, dict):
            continue
        snapshots.extend(_snapshot_entries_from_data(data))
    return snapshots


def _snapshot_entries_from_data(data: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(data.get("snapshots"), list):
        hints = _restore_hints_by_path(data.get("restore_hints"))
        entries = []
        for snapshot in data["snapshots"]:
            if not isinstance(snapshot, dict):
                continue
            path = snapshot.get("path")
            snapshot_path = snapshot.get("snapshot_path")
            if not path or not snapshot_path:
                continue
            entries.append(
                {
                    "path": str(path),
                    "snapshot_path": str(snapshot_path),
                    "restore_hint": hints.get(str(path), ""),
                }
            )
        return entries

    path = data.get("path")
    snapshot_path = data.get("snapshot_path")
    restore_hint = data.get("restore_hint")
    if path and snapshot_path:
        return [
            {
                "path": str(path),
                "snapshot_path": str(snapshot_path),
                "restore_hint": str(restore_hint or ""),
            }
        ]
    return []


def _restore_hints_by_path(raw_restore_hints: Any) -> dict[str, str]:
    if not isinstance(raw_restore_hints, list):
        return {}
    result: dict[str, str] = {}
    for item in raw_restore_hints:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        hint = item.get("hint")
        if path and hint:
            result[str(path)] = str(hint)
    return result


def _datetime_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _is_within(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root))
    try:
        return os.path.commonpath([path_text, root_text]) == root_text
    except ValueError:
        return False
