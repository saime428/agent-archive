from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.actions import (
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
    parse_model_action,
)
from agent.core.context import RunContext
from agent.llm.base import LLMClient


@dataclass(frozen=True)
class RunResult:
    context: RunContext
    action: InternalAction
    observation: Observation
    summary_path: Path
    tool_calls_path: Path


def run_once(
    task: str,
    llm: LLMClient,
    *,
    cwd: Path | None = None,
    run_id: str | None = None,
) -> RunResult:
    context = RunContext.create(task=task, cwd=cwd, run_id=run_id)
    raw_response = llm.chat([{"role": "user", "content": task}])
    action = parse_model_action(
        raw_response,
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    if action.action.name == "done":
        observation = make_observation(
            action,
            observation_index=1,
            summary="Done.",
            data={"final": str(action.action.args["final"])},
        )
    else:
        observation = make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=1,
            code=ErrorCode.POLICY_DENIED,
            message="Only done actions are supported in the current run loop.",
            details={"requested_action": action.action.name},
        )

    run_dir = context.cwd / ".agent" / "runs" / context.run_id
    tool_calls_path = run_dir / "tool_calls.jsonl"
    summary_path = run_dir / "summary.md"
    _write_run_logs(
        context=context,
        action=action,
        observation=observation,
        tool_calls_path=tool_calls_path,
        summary_path=summary_path,
    )
    return RunResult(
        context=context,
        action=action,
        observation=observation,
        summary_path=summary_path,
        tool_calls_path=tool_calls_path,
    )


def _write_run_logs(
    *,
    context: RunContext,
    action: InternalAction,
    observation: Observation,
    tool_calls_path: Path,
    summary_path: Path,
) -> None:
    tool_calls_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "action": action.model_dump(mode="json"),
        "observation": observation.model_dump(mode="json"),
    }
    tool_calls_path.write_text(
        json.dumps(record, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(_render_summary(context, action, observation), encoding="utf-8")


def _render_summary(
    context: RunContext,
    action: InternalAction,
    observation: Observation,
) -> str:
    lines = [
        f"# Run {context.run_id}",
        "",
        f"- task: {context.task}",
        f"- action: {action.action.name}",
        f"- status: {observation.status}",
    ]
    final = _final_from_observation(observation)
    if final:
        lines.append(f"- final: {final}")
    if observation.error:
        lines.append(f"- error: {observation.error.code}: {observation.error.message}")
    lines.append("")
    return "\n".join(lines)


def _final_from_observation(observation: Observation) -> str | None:
    data: dict[str, Any] | None = observation.data
    if not data:
        return None
    final = data.get("final")
    if final is None:
        return None
    return str(final)
