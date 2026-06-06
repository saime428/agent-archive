from __future__ import annotations

import fnmatch
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from agent.core.actions import (
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
)
from agent.core.context import RunContext
from agent.policy.sandbox import SandboxError, WorkspaceSandbox

DEFAULT_MAX_LINES = 200
DEFAULT_MAX_CHARS = 20_000
DEFAULT_MAX_MATCHES = 50
MAX_EXCERPT_CHARS = 200
SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache"}


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_path: Path
    previously_existed: bool
    restore_hint: str


@dataclass(frozen=True)
class PatchFilePlan:
    path: Path
    original_text: str
    patched_text: str
    replacements: int


def execute_tool(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    try:
        if action.action.name == "list_dir":
            return _list_dir(action, sandbox, observation_index=observation_index)
        if action.action.name == "read_file":
            return _read_file(action, sandbox, observation_index=observation_index)
        if action.action.name == "search_files":
            return _search_files(action, sandbox, observation_index=observation_index)
        if action.action.name == "write_file":
            return _write_file(action, context, sandbox, observation_index=observation_index)
        if action.action.name == "apply_patch":
            return _apply_patch(action, context, sandbox, observation_index=observation_index)
    except SandboxError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    except OSError as exc:
        return make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message=str(exc),
            details={"tool": action.action.name},
        )

    return make_error_observation(
        action.action_id,
        context.run_id,
        observation_index=observation_index,
        code=ErrorCode.POLICY_DENIED,
        message="Unsupported tool.",
        details={"requested_action": action.action.name},
    )


def _apply_patch(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    plans = _plan_patch_files(action, sandbox)
    snapshots: list[dict] = []
    restore_hints: list[dict] = []

    for index, plan in enumerate(plans, start=1):
        snapshot = create_snapshot(
            plan.path,
            context,
            action_id=action.action_id,
            snapshot_name=f"file_{index:06d}",
        )
        snapshots.append(
            {
                "path": str(plan.path),
                "snapshot_path": _display_path(snapshot.snapshot_path, context.cwd),
                "previously_existed": snapshot.previously_existed,
            }
        )
        restore_hints.append({"path": str(plan.path), "hint": snapshot.restore_hint})

    for plan in plans:
        plan.path.write_bytes(plan.patched_text.encode("utf-8"))

    replacements = [{"path": str(plan.path), "count": plan.replacements} for plan in plans]
    changed_files = [str(plan.path) for plan in plans]
    total_replacements = sum(plan.replacements for plan in plans)
    data = {
        "changed_files": changed_files,
        "snapshots": snapshots,
        "replacements": replacements,
        "restore_hints": restore_hints,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Applied patch to {len(plans)} files with {total_replacements} replacements.",
        data=data,
    )


def _plan_patch_files(action: InternalAction, sandbox: WorkspaceSandbox) -> list[PatchFilePlan]:
    plans_by_path: dict[Path, PatchFilePlan] = {}
    ordered_paths: list[Path] = []

    for edit in action.action.args["edits"]:
        path = sandbox.resolve_write_path(str(edit["path"]), create_parents=False)
        if not path.is_file():
            raise OSError(f"Not a file: {path}")

        if path in plans_by_path:
            plan = plans_by_path[path]
            current_text = plan.patched_text
            original_text = plan.original_text
            replacement_total = plan.replacements
        else:
            raw = path.read_bytes()
            if _looks_binary(raw):
                raise OSError("Binary files are not supported by apply_patch.")
            current_text = _decode_text(raw)
            original_text = current_text
            replacement_total = 0
            ordered_paths.append(path)

        old = str(edit["old"])
        new = str(edit["new"])
        occurrence = str(edit["occurrence"])
        match_count = current_text.count(old)
        if match_count == 0:
            raise OSError(f"Patch text not found in file: {path}")
        if occurrence == "first" and match_count != 1:
            raise OSError(f"Patch text is ambiguous in file: {path}")

        replacement_count = 1 if occurrence == "first" else match_count
        patched_text = current_text.replace(old, new, replacement_count)
        plans_by_path[path] = PatchFilePlan(
            path=path,
            original_text=original_text,
            patched_text=patched_text,
            replacements=replacement_total + replacement_count,
        )

    return [plans_by_path[path] for path in ordered_paths]


def _write_file(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    path = sandbox.resolve_write_path(
        str(action.action.args["path"]),
        create_parents=bool(action.action.args["create_parents"]),
    )
    content = str(action.action.args["content"])
    snapshot = create_snapshot(path, context, action_id=action.action_id)
    if action.action.args["create_parents"]:
        path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    path.write_bytes(encoded)

    data = {
        "path": str(path),
        "bytes_written": len(encoded),
        "snapshot_path": _display_path(snapshot.snapshot_path, context.cwd),
        "previously_existed": snapshot.previously_existed,
        "restore_hint": snapshot.restore_hint,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Wrote {len(encoded)} bytes to file.",
        data=data,
    )


def create_snapshot(
    path: Path,
    context: RunContext,
    *,
    action_id: str,
    snapshot_name: str | None = None,
) -> SnapshotRecord:
    snapshot_dir = context.cwd / ".agent" / "runs" / context.run_id / "snapshots" / action_id
    if snapshot_name is not None:
        snapshot_dir = snapshot_dir / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    metadata_path = snapshot_dir / "metadata.json"
    content_snapshot_path = snapshot_dir / "original"
    metadata = {
        "path": str(path),
        "action_id": action_id,
        "previously_existed": existed,
    }

    if existed:
        shutil.copy2(path, content_snapshot_path)
        metadata["snapshot_file"] = str(content_snapshot_path)
        metadata["byte_size"] = path.stat().st_size
        snapshot_path = content_snapshot_path
        restore_hint = f"Restore by copying {content_snapshot_path} back to {path}."
    else:
        metadata["snapshot_file"] = None
        metadata["byte_size"] = None
        snapshot_path = metadata_path
        restore_hint = f"Restore by deleting {path}."

    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return SnapshotRecord(
        snapshot_path=snapshot_path,
        previously_existed=existed,
        restore_hint=restore_hint,
    )


def _list_dir(
    action: InternalAction,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    path = sandbox.resolve_read_path(str(action.action.args["path"]))
    if not path.is_dir():
        raise OSError(f"Not a directory: {path}")

    entries = sorted(path.iterdir(), key=lambda item: item.name.lower())
    max_entries = action.action.args.get("max_entries")
    visible_entries = entries[:max_entries] if max_entries is not None else entries
    data = {
        "path": str(path),
        "total_entries": len(entries),
        "truncated": max_entries is not None and len(entries) > max_entries,
        "entries": [
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
            for item in visible_entries
        ],
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Listed {len(visible_entries)} of {len(entries)} entries.",
        data=data,
    )


def _read_file(
    action: InternalAction,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    path = sandbox.resolve_read_path(str(action.action.args["path"]))
    if not path.is_file():
        raise OSError(f"Not a file: {path}")

    raw = path.read_bytes()
    if _looks_binary(raw):
        return make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=observation_index,
            code=ErrorCode.TOOL_FAILED,
            message="Binary files are not supported by read_file.",
            details={"path": str(path)},
        )

    text = _decode_text(raw)
    lines = text.splitlines()
    total_lines = len(lines)
    start_line = action.action.args.get("start_line") or 1
    requested_max_lines = action.action.args.get("max_lines")
    max_lines = requested_max_lines or DEFAULT_MAX_LINES
    start_index = max(start_line - 1, 0)
    selected_lines = lines[start_index : start_index + max_lines]
    content = "\n".join(selected_lines)
    truncated = requested_max_lines is None and start_index + len(selected_lines) < total_lines
    if len(content) > DEFAULT_MAX_CHARS:
        content = content[:DEFAULT_MAX_CHARS]
        truncated = True
    if truncated:
        content = f"{content}\n[truncated]" if content else "[truncated]"
    end_line = start_line + len(selected_lines) - 1 if selected_lines else start_line - 1

    data = {
        "path": str(path),
        "content": content,
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": total_lines,
        "byte_size": len(raw),
        "truncated": truncated,
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Read {len(selected_lines)} lines from file.",
        data=data,
    )


def _search_files(
    action: InternalAction,
    sandbox: WorkspaceSandbox,
    *,
    observation_index: int,
) -> Observation:
    query = str(action.action.args["query"])
    requested_path = action.action.args.get("path") or "."
    root = sandbox.resolve_read_path(str(requested_path))
    max_matches = action.action.args.get("max_matches") or DEFAULT_MAX_MATCHES
    glob_mode = _is_glob_query(query)
    matches: list[dict] = []
    total_matches = 0

    paths = [root] if root.is_file() else sorted(root.rglob("*"), key=lambda item: str(item).lower())
    for candidate in paths:
        if _should_skip_path(candidate, sandbox.root):
            continue
        if candidate.is_dir():
            continue
        relative_path = candidate.relative_to(sandbox.root).as_posix()
        candidate_matches = (
            _path_matches(relative_path, query)
            if glob_mode
            else _path_and_text_matches(candidate, relative_path, query)
        )
        for match in candidate_matches:
            total_matches += 1
            if len(matches) < max_matches:
                matches.append(match)

    data = {
        "query": query,
        "path": str(root),
        "matches": matches,
        "total_matches": total_matches,
        "truncated": total_matches > len(matches),
    }
    return make_observation(
        action,
        observation_index=observation_index,
        summary=f"Found {len(matches)} of {total_matches} matches.",
        data=data,
    )


def _is_glob_query(query: str) -> bool:
    return any(char in query for char in "*?[]")


def _path_matches(relative_path: str, query: str) -> list[dict]:
    name = Path(relative_path).name
    if fnmatch.fnmatchcase(relative_path, query) or fnmatch.fnmatchcase(name, query):
        return [{"path": relative_path, "kind": "path", "line": None, "excerpt": None}]
    return []


def _path_and_text_matches(candidate: Path, relative_path: str, query: str) -> list[dict]:
    query_lower = query.lower()
    matches: list[dict] = []
    if query_lower in relative_path.lower():
        matches.append({"path": relative_path, "kind": "path", "line": None, "excerpt": None})

    raw = candidate.read_bytes()
    if _looks_binary(raw):
        return matches

    text = _decode_text(raw)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if query_lower in line.lower():
            matches.append(
                {
                    "path": relative_path,
                    "kind": "text",
                    "line": line_number,
                    "excerpt": _excerpt(line),
                }
            )
    return matches


def _should_skip_path(candidate: Path, workspace_root: Path) -> bool:
    try:
        relative_parts = candidate.relative_to(workspace_root).parts
    except ValueError:
        return True
    if len(relative_parts) >= 2 and relative_parts[0] == ".agent" and relative_parts[1] == "runs":
        return True
    return any(part in SKIP_DIR_NAMES for part in relative_parts)


def _excerpt(line: str) -> str:
    if len(line) <= MAX_EXCERPT_CHARS:
        return line
    return line[:MAX_EXCERPT_CHARS]


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:4096]


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(path)
