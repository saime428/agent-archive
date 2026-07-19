from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.run_store import RunStore, RunStoreError


def build_runs_payload(workspace: Path, *, limit: int = 20) -> dict[str, Any]:
    store = RunStore(workspace.resolve())
    runs = store.list_runs(limit=limit)
    return {
        "workspace": str(workspace.resolve()),
        "runs": [_build_run_list_item(store, run) for run in runs],
    }


def _build_run_list_item(store: RunStore, run: Any) -> dict[str, Any]:
    item = {
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "summary_path": str(run.summary_path),
        "tool_calls_path": str(run.tool_calls_path),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "status": "unknown",
        "risk_level": "attention",
    }
    try:
        detail = store.show_run(run.run_id)
    except RunStoreError:
        return item

    review = _build_task_review(detail.tool_calls, detail.snapshots)
    failure = build_failure_summary(detail.tool_calls)
    workflow = _build_workflow_hints(review)
    item["status"] = _summary_field(detail.summary, "status") or "unknown"
    item["risk_level"] = _build_patch_review(review, workflow, failure)["risk_level"]
    return item


def _summary_field(summary: str, name: str) -> str | None:
    prefix = f"- {name}: "
    for line in summary.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def build_run_detail_payload(workspace: Path, run_id: str) -> dict[str, Any]:
    detail = RunStore(workspace.resolve()).show_run(run_id)
    review = _build_task_review(detail.tool_calls, detail.snapshots)
    failure = build_failure_summary(detail.tool_calls)
    workflow = _build_workflow_hints(review)
    return {
        "run_id": detail.run_id,
        "run_dir": str(detail.run_dir),
        "summary": detail.summary,
        "tool_calls": [
            {
                "line_number": call.line_number,
                "valid": call.valid,
                "raw": call.raw,
                "data": call.data,
                "error": call.error,
            }
            for call in detail.tool_calls
        ],
        "snapshots": detail.snapshots,
        "review": review,
        "workflow": workflow,
        "failure": failure,
        "patch_review": _build_patch_review(review, workflow, failure),
        "recovery": _build_failure_recovery(review, workflow, failure),
        "replay": build_run_replay(detail.tool_calls),
    }


def _build_task_review(tool_calls: list[Any], snapshots: list[dict[str, str]]) -> dict[str, Any]:
    latest_action = "none"
    last_observation_summary = "No observation recorded."
    changed_files: list[str] = []

    for call in tool_calls:
        if not call.valid or not call.data:
            continue
        action = call.data.get("action")
        if isinstance(action, dict):
            inner_action = action.get("action")
            if isinstance(inner_action, dict):
                latest_action = str(inner_action.get("name") or latest_action)
                args = inner_action.get("args")
                if isinstance(args, dict):
                    raw_changed_files = args.get("changed_files")
                    if isinstance(raw_changed_files, list):
                        changed_files.extend(str(path) for path in raw_changed_files if path)
        observation = call.data.get("observation")
        if isinstance(observation, dict):
            last_observation_summary = str(observation.get("summary") or last_observation_summary)

    changed_files.extend(str(snapshot.get("path")) for snapshot in snapshots if snapshot.get("path"))
    unique_changed_files = list(dict.fromkeys(changed_files))
    if unique_changed_files:
        manual_checks = ["Open the changed files and review the saved summary."]
    else:
        manual_checks = ["Review the summary and trace for the final status."]
    if snapshots:
        manual_checks.append("Use Show diff before Restore when checking snapshot-backed changes.")

    return {
        "latest_action": latest_action,
        "last_observation_summary": last_observation_summary,
        "changed_files": unique_changed_files,
        "snapshot_count": len(snapshots),
        "manual_checks": manual_checks,
    }


def _build_workflow_hints(review: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(path) for path in review.get("changed_files", []) if path]
    commands: list[str] = []
    if any(path.startswith("src/agent/web/") or path == "tests/test_ui.py" for path in changed_files):
        commands.append("python -m pytest tests/test_ui.py -q")
    if any(path == "README.md" or path.startswith("docs/") or path == "tests/test_docs.py" for path in changed_files):
        commands.append("python -m pytest tests/test_docs.py -q")
    if any(path.endswith(".py") for path in changed_files):
        commands.append("python -m pytest -q")
    if changed_files:
        commands.append("git diff --check")
    if not commands:
        commands.append("Review the summary and trace before taking action.")

    return {
        "mode": "read-only",
        "verification_commands": list(dict.fromkeys(commands)),
        "review_steps": [
            "Open changed files from Task Review.",
            "Run the suggested verification commands before committing.",
        ],
    }


def build_failure_summary(tool_calls: list[Any]) -> dict[str, Any]:
    failures = []
    for call in tool_calls:
        failure = _failure_from_tool_call(call)
        if failure is not None:
            failures.append(failure)

    if not failures:
        return {
            "status": "clear",
            "failure_count": 0,
            "latest_failure": None,
            "next_checks": ["No failed observations recorded for this run."],
        }

    return {
        "status": "failed",
        "failure_count": len(failures),
        "latest_failure": failures[-1],
        "next_checks": [
            "Read the failed observation summary.",
            "Inspect the trace around the failed action.",
            "Use Workflow Hints before changing code.",
        ],
    }


def _build_patch_review(
    review: dict[str, Any],
    workflow: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    commands = list(workflow.get("verification_commands", []))
    changed_files = list(review.get("changed_files", []))
    snapshot_count = int(review.get("snapshot_count") or 0)

    if failure.get("failure_count"):
        return {
            "mode": "read-only",
            "risk_level": "attention",
            "summary": "Failed observations need review before patching.",
            "checks": [
                "Read Failure Summary before changing code.",
                "Inspect the trace around the failed action.",
                "Run verification commands only from a terminal.",
            ],
            "verification_commands": commands,
            "next_action": "Resolve or explain the failed observation before patching.",
        }

    if changed_files or snapshot_count:
        checks = ["Open changed files from Task Review."]
        if snapshot_count:
            checks.append("Use Show diff before Restore when checking snapshots.")
        checks.append("Run suggested verification commands from Workflow Hints.")
        return {
            "mode": "read-only",
            "risk_level": "medium",
            "summary": f"{len(changed_files)} changed file(s), {snapshot_count} snapshot(s), no failed observations.",
            "checks": checks,
            "verification_commands": commands,
            "next_action": "Review changes and run suggested verification commands from a terminal.",
        }

    return {
        "mode": "read-only",
        "risk_level": "low",
        "summary": "No failed observations or changed files recorded.",
        "checks": ["Review the summary and trace before taking action."],
        "verification_commands": commands,
        "next_action": "No patch review action needed.",
    }


def _build_failure_recovery(
    review: dict[str, Any],
    workflow: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    commands = list(workflow.get("verification_commands", []))
    snapshot_count = int(review.get("snapshot_count") or 0)
    rollback_available = snapshot_count > 0
    latest_failure = failure.get("latest_failure")

    if failure.get("failure_count"):
        steps = [
            "Inspect the failed action in Trace.",
            "Read Failure Summary before changing files.",
        ]
        if rollback_available:
            steps.append("Use Show diff before Restore when checking snapshots.")
        else:
            steps.append("Check the workspace manually before retrying.")
        return {
            "mode": "read-only",
            "status": "needs-attention",
            "rollback_available": rollback_available,
            "summary": "Failed observations need a recovery decision before more changes.",
            "latest_failure": latest_failure,
            "steps": steps,
            "checks": [
                "Do not retry tools from the browser.",
                "Run verification from a terminal after patching.",
            ],
            "verification_commands": commands,
            "next_action": "Inspect the failure, then patch or retry from a terminal workflow.",
        }

    if rollback_available:
        return {
            "mode": "read-only",
            "status": "snapshot-review",
            "rollback_available": True,
            "summary": f"{snapshot_count} snapshot(s) are available for manual review.",
            "latest_failure": None,
            "steps": ["Open Snapshots and use Show diff before any restore."],
            "checks": ["Restore only after confirming the diff."],
            "verification_commands": commands,
            "next_action": "Review snapshots before making further file changes.",
        }

    return {
        "mode": "read-only",
        "status": "clear",
        "rollback_available": False,
        "summary": "No failed observations or rollback snapshots recorded.",
        "latest_failure": None,
        "steps": ["No recovery action needed."],
        "checks": ["Review the summary and trace before taking action."],
        "verification_commands": commands,
        "next_action": "No recovery action needed.",
    }


def build_run_replay(tool_calls: list[Any]) -> dict[str, Any]:
    steps = [_replay_step_from_tool_call(call) for call in tool_calls]
    return {
        "mode": "read-only",
        "step_count": len(steps),
        "steps": steps,
    }


def _replay_step_from_tool_call(call: Any) -> dict[str, Any]:
    if not call.valid or not call.data:
        return {
            "line_number": call.line_number,
            "phase": "parse",
            "action": "invalid",
            "status": "invalid",
            "summary": call.error or "Invalid tool call log record.",
            "terminal": True,
            "policy_decision": "",
        }

    action = call.data.get("action")
    inner_action = action.get("action") if isinstance(action, dict) else None
    observation = call.data.get("observation")
    trace = call.data.get("trace")
    return {
        "line_number": call.line_number,
        "phase": str(trace.get("phase") or "action") if isinstance(trace, dict) else "action",
        "action": str(inner_action.get("name") or "unknown") if isinstance(inner_action, dict) else "unknown",
        "status": str(observation.get("status") or "unknown") if isinstance(observation, dict) else "unknown",
        "summary": str(observation.get("summary") or "No observation summary.")
        if isinstance(observation, dict)
        else "No observation summary.",
        "terminal": bool(trace.get("terminal")) if isinstance(trace, dict) else False,
        "policy_decision": str(trace.get("policy_decision") or "") if isinstance(trace, dict) else "",
    }


def _failure_from_tool_call(call: Any) -> dict[str, Any] | None:
    if not call.valid or not call.data:
        return {
            "line_number": call.line_number,
            "action": "invalid",
            "status": "invalid",
            "summary": call.error or "Invalid tool call log record.",
            "error_code": "INVALID_LOG_RECORD",
        }

    action = call.data.get("action")
    action_name = "unknown"
    if isinstance(action, dict):
        inner_action = action.get("action")
        if isinstance(inner_action, dict):
            action_name = str(inner_action.get("name") or action_name)

    observation = call.data.get("observation")
    if not isinstance(observation, dict):
        return None
    status = str(observation.get("status") or "")
    if status == "ok":
        return None

    error = observation.get("error")
    error_code = ""
    error_message = ""
    if isinstance(error, dict):
        error_code = str(error.get("code") or "")
        error_message = str(error.get("message") or "")
    summary = str(observation.get("summary") or error_message or "No failure summary.")
    return {
        "line_number": call.line_number,
        "action": action_name,
        "status": status or "error",
        "summary": summary,
        "error_code": error_code,
    }
