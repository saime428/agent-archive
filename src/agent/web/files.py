from __future__ import annotations

import difflib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.core.actions import ActionCall, InternalAction, make_observation
from agent.core.budget import ContextBudget, truncate_text
from agent.core.context import RunContext
from agent.core.redaction import redact_record, redact_value
from agent.policy.sandbox import SandboxError, WorkspaceSandbox
from agent.tools.filesystem import create_snapshot


def _read_sandbox(root: Path) -> WorkspaceSandbox:
    config, _diagnostics = load_config(root.resolve())
    return WorkspaceSandbox(root, allow_external_read=config.computer_read_enabled)


def build_files_payload(workspace: Path, path: str | None = None) -> dict[str, Any]:
    root = workspace.resolve()
    sandbox = _read_sandbox(root)
    requested = path or "."
    try:
        directory = sandbox.resolve_read_path(requested)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not directory.exists():
        raise ValueError(f"Directory not found: {requested}")
    if not directory.is_dir():
        raise ValueError(f"Path is not a directory: {requested}")
    entries = []
    for entry in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": entry.name,
                "path": _display_path(entry, root),
                "kind": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            }
        )
    return {"path": _display_path(directory, root), "entries": entries}


def build_file_payload(workspace: Path, path: str | None, *, max_chars: int | None = None) -> dict[str, Any]:
    if not path:
        raise ValueError("path is required.")
    root = workspace.resolve()
    sandbox = _read_sandbox(root)
    try:
        file_path = sandbox.resolve_read_path(path)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    budget = ContextBudget()
    limit = min(max_chars or budget.file_read_max_chars, budget.file_read_max_chars)
    with file_path.open("rb") as handle:
        sample = handle.read(min(limit, 4096))
    if b"\x00" in sample:
        raise ValueError(f"Binary file preview is not supported: {path}")
    content = file_path.read_text(encoding="utf-8", errors="replace")
    truncated = truncate_text(content, limit)
    return {
        "path": _display_path(file_path, root),
        "content": truncated.value,
        "truncated": truncated.truncated,
        "size": file_path.stat().st_size,
    }


def build_save_file_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    path = request.get("path")
    content = request.get("content")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required.")
    if not isinstance(content, str):
        raise ValueError("content is required.")

    root = workspace.resolve()
    try:
        file_path = WorkspaceSandbox(root).resolve_write_path(path, create_parents=False)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    with file_path.open("rb") as handle:
        if b"\x00" in handle.read(4096):
            raise ValueError(f"Binary file editing is not supported: {path}")

    context = RunContext.create("Workbench file editor save", cwd=root)
    action = InternalAction(
        run_id=context.run_id,
        action_id="act_000001",
        created_at=context.created_at,
        message="Workbench file editor save.",
        action=ActionCall(
            name="write_file",
            args={
                "path": _display_path(file_path, root),
                "source": "workbench-file-editor",
                "bytes": len(content.encode("utf-8")),
            },
        ),
    )
    snapshot = create_snapshot(file_path, context, action_id=action.action_id)
    encoded = content.encode("utf-8")
    file_path.write_bytes(encoded)
    observation = make_observation(
        action,
        observation_index=1,
        summary=f"Saved {len(encoded)} bytes from Workbench file editor.",
        data={
            "path": _display_path(file_path, root),
            "bytes_written": len(encoded),
            "snapshot_path": _display_path(snapshot.snapshot_path, root),
            "previously_existed": snapshot.previously_existed,
            "restore_hint": snapshot.restore_hint,
        },
    )
    _write_workbench_file_save_log(context, action, observation)
    return {
        "status": "ok",
        "run_id": context.run_id,
        "path": _display_path(file_path, root),
        "bytes_written": len(encoded),
        "snapshot_path": _display_path(snapshot.snapshot_path, root),
        "restore_hint": snapshot.restore_hint,
    }


def build_diff_payload(
    workspace: Path,
    path: str | None,
    snapshot: str | None,
    *,
    max_chars: int | None = None,
) -> dict[str, Any]:
    if not path:
        raise ValueError("path is required.")
    if not snapshot:
        raise ValueError("snapshot is required.")
    root = workspace.resolve()
    sandbox = WorkspaceSandbox(root)
    try:
        current_path = sandbox.resolve_read_path(path)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc
    snapshot_path = _resolve_snapshot_path(root, snapshot)

    old_text, snapshot_missing = _snapshot_text(snapshot_path, snapshot)
    new_text = "" if not current_path.exists() else _read_text_for_diff(current_path, path)
    display_path = _display_path(current_path, root)
    diff = "\n".join(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"snapshot/{display_path}",
            tofile=f"current/{display_path}",
            lineterm="",
        )
    )
    budget = ContextBudget()
    limit = min(max_chars or budget.file_read_max_chars, budget.file_read_max_chars)
    truncated = truncate_text(diff, limit)
    return {
        "path": display_path,
        "snapshot_path": _display_path(snapshot_path, root),
        "diff": truncated.value,
        "truncated": truncated.truncated,
        "current_exists": current_path.exists(),
        "snapshot_missing": snapshot_missing,
    }


def build_restore_snapshot_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    path = request.get("path")
    snapshot = request.get("snapshot_path")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required.")
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("snapshot_path is required.")

    root = workspace.resolve()
    snapshot_path = _resolve_snapshot_path(root, snapshot)
    metadata = _snapshot_metadata(snapshot_path)
    target_path = _restore_target_path(root, str(metadata.get("path") or path))
    previously_existed = metadata.get("previously_existed")
    if not isinstance(previously_existed, bool):
        raise ValueError("Snapshot metadata is missing previously_existed.")

    if previously_existed:
        original = _resolve_snapshot_path(root, str(metadata.get("snapshot_file") or snapshot))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target_path)
        action = "restored"
    else:
        if target_path.exists():
            if not target_path.is_file():
                raise ValueError(f"Restore target is not a file: {path}")
            target_path.unlink()
        action = "deleted"

    return {
        "status": "ok",
        "action": action,
        "path": _display_path(target_path, root),
        "snapshot_path": _display_path(snapshot_path, root),
    }


def _display_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    value = relative.as_posix()
    return value or "."


def _resolve_snapshot_path(root: Path, snapshot: str) -> Path:
    requested = Path(snapshot)
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve()
    runs_root = (root / ".agent" / "runs").resolve()
    if not _is_within(resolved, runs_root):
        raise ValueError("SANDBOX_VIOLATION: Snapshot path must stay under .agent/runs.")
    relative_parts = resolved.relative_to(runs_root).parts
    if len(relative_parts) < 3 or relative_parts[1] != "snapshots":
        raise ValueError("SANDBOX_VIOLATION: Snapshot path must stay under .agent/runs snapshots.")
    if not resolved.exists():
        raise ValueError(f"Snapshot not found: {snapshot}")
    if not resolved.is_file():
        raise ValueError(f"Snapshot path is not a file: {snapshot}")
    return resolved


def _snapshot_text(path: Path, requested: str) -> tuple[str, bool]:
    if path.name == "metadata.json":
        metadata = _read_json_file(path)
        if isinstance(metadata, dict) and metadata.get("previously_existed") is False:
            return "", True
    return _read_text_for_diff(path, requested), False


def _snapshot_metadata(snapshot_path: Path) -> dict[str, Any]:
    metadata_path = snapshot_path if snapshot_path.name == "metadata.json" else snapshot_path.parent / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError(f"Snapshot metadata missing: {metadata_path}")
    metadata = _read_json_file(metadata_path)
    if not isinstance(metadata, dict):
        raise ValueError(f"Snapshot metadata must be an object: {metadata_path}")
    return metadata


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid snapshot metadata: {path}") from exc


def _restore_target_path(root: Path, path: str) -> Path:
    try:
        return WorkspaceSandbox(root).resolve_write_path(path, create_parents=True)
    except SandboxError as exc:
        raise ValueError(f"{exc.code}: {exc.message}") from exc


def _read_text_for_diff(path: Path, label: str) -> str:
    if path.is_dir():
        raise ValueError(f"Diff path is not a file: {label}")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError(f"Binary diff is not supported: {label}")
    return raw.decode("utf-8", errors="replace")


def _write_workbench_file_save_log(context: RunContext, action: InternalAction, observation: Any) -> None:
    run_dir = context.cwd / ".agent" / "runs" / context.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "action": action.model_dump(mode="json"),
        "observation": observation.model_dump(mode="json"),
        "trace": {
            "phase": "workbench",
            "action_index": 1,
            "observation_index": 1,
            "repair_attempt": 0,
            "terminal": True,
        },
    }
    redacted_record = redact_record(record)
    serialized_record = redacted_record.value
    if redacted_record.applied:
        serialized_record["redaction"] = {
            "applied": True,
            "replacements": redacted_record.replacements,
        }
    (run_dir / "tool_calls.jsonl").write_text(
        json.dumps(serialized_record, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    data = observation.data or {}
    summary = "\n".join(
        [
            f"# Run {context.run_id}",
            "",
            "- task: Workbench file editor save",
            "- action: write_file",
            f"- status: {observation.status}",
            "- completed: true",
            "- terminal_reason: workbench_file_save",
            "- final: Saved file from Workbench file editor.",
            f"- last_action: {action.action.name}",
            f"- last_observation_summary: {observation.summary}",
            "",
            "## Changed Files",
            f"- changed_file: {data.get('path', '')}",
            f"- snapshot: {data.get('snapshot_path', '')}",
            f"- restore: {data.get('restore_hint', '')}",
            "",
        ]
    )
    redacted_summary = redact_value(summary)
    summary_text = redacted_summary.value
    if redacted_summary.applied:
        summary_text = summary_text.rstrip("\n") + "\n- redaction_applied: true\n"
    (run_dir / "summary.md").write_text(summary_text, encoding="utf-8")


def _is_within(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root))
    try:
        return os.path.commonpath([path_text, root_text]) == root_text
    except ValueError:
        return False
