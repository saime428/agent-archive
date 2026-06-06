from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.core.actions import (
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
    parse_model_action,
)
from agent.core.context import RunContext
from agent.core.project_instructions import (
    ProjectInstructions,
    build_project_instructions_message,
    load_project_instructions,
)
from agent.llm.base import LLMClient
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.filesystem import execute_tool
from agent.tools.git import execute_git_tool
from agent.tools.shell import execute_run_command


@dataclass(frozen=True)
class RunResult:
    context: RunContext
    action: InternalAction
    observation: Observation
    observations: list[Observation]
    summary_path: Path
    tool_calls_path: Path
    project_instructions: ProjectInstructions
    config: AgentConfig


def run_once(
    task: str,
    llm: LLMClient,
    *,
    cwd: Path | None = None,
    run_id: str | None = None,
    max_iterations: int = 3,
    config: AgentConfig | None = None,
) -> RunResult:
    effective_config = config or AgentConfig()
    context = RunContext.create(task=task, cwd=cwd, run_id=run_id)
    run_dir = context.cwd / ".agent" / "runs" / context.run_id
    tool_calls_path = run_dir / "tool_calls.jsonl"
    summary_path = run_dir / "summary.md"
    sandbox = WorkspaceSandbox(context.cwd)
    project_instructions = load_project_instructions(context.cwd)
    messages = _build_messages(task, project_instructions)
    actions: list[InternalAction] = []
    observations: list[Observation] = []

    for action_index in range(1, max_iterations + 1):
        raw_response = llm.chat(messages)
        action = parse_model_action(
            raw_response,
            run_id=context.run_id,
            action_index=action_index,
            created_at=context.created_at,
        )
        actions.append(action)

        if action.action.name == "done":
            observation = make_observation(
                action,
                observation_index=action_index,
                summary="Done.",
                data={"final": str(action.action.args["final"])},
            )
        elif action.action.name in {
            "list_dir",
            "read_file",
            "search_files",
            "write_file",
            "apply_patch",
        }:
            observation = execute_tool(
                action,
                context,
                sandbox,
                observation_index=action_index,
            )
        elif action.action.name == "run_command":
            observation = execute_run_command(
                action,
                context,
                sandbox,
                observation_index=action_index,
            )
        elif action.action.name in {"git_status", "git_diff"}:
            observation = execute_git_tool(
                action,
                context,
                sandbox,
                observation_index=action_index,
            )
        else:
            observation = make_error_observation(
                action.action_id,
                action.run_id,
                observation_index=action_index,
                code=ErrorCode.POLICY_DENIED,
                message="This action is not supported in the current run loop.",
                details={"requested_action": action.action.name},
            )
        observations.append(observation)
        if action.action.name == "done" or observation.status == "error":
            break
    else:
        action = actions[-1]
        observation = make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=max_iterations + 1,
            code=ErrorCode.TOOL_FAILED,
            message="Run stopped after reaching the iteration limit.",
            details={"max_iterations": max_iterations},
        )
        observations.append(observation)

    _write_run_logs(
        context=context,
        actions=actions,
        observations=observations,
        project_instructions=project_instructions,
        config=effective_config,
        tool_calls_path=tool_calls_path,
        summary_path=summary_path,
    )
    return RunResult(
        context=context,
        action=actions[-1],
        observation=observations[-1],
        observations=observations,
        summary_path=summary_path,
        tool_calls_path=tool_calls_path,
        project_instructions=project_instructions,
        config=effective_config,
    )


def _build_messages(task: str, project_instructions: ProjectInstructions) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    project_message = build_project_instructions_message(project_instructions)
    if project_message is not None:
        messages.append(project_message)
    messages.append({"role": "user", "content": task})
    return messages


def _write_run_logs(
    *,
    context: RunContext,
    actions: list[InternalAction],
    observations: list[Observation],
    project_instructions: ProjectInstructions,
    config: AgentConfig,
    tool_calls_path: Path,
    summary_path: Path,
) -> None:
    tool_calls_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for action, observation in zip(actions, observations, strict=False):
        records.append(
            json.dumps(
                {
                    "action": action.model_dump(mode="json"),
                    "observation": observation.model_dump(mode="json"),
                },
                ensure_ascii=True,
            )
        )
    tool_calls_path.write_text(
        "\n".join(records) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        _render_summary(context, actions, observations, project_instructions, config),
        encoding="utf-8",
    )


def _render_summary(
    context: RunContext,
    actions: list[InternalAction],
    observations: list[Observation],
    project_instructions: ProjectInstructions,
    config: AgentConfig,
) -> str:
    action = actions[-1]
    observation = observations[-1]
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
    lines.extend(_project_instruction_lines(project_instructions))
    lines.extend(_config_lines(config))
    changed_lines = _changed_file_lines(observations)
    if changed_lines:
        lines.extend(["", "## Changes", *changed_lines])
    lines.append("")
    return "\n".join(lines)


def _project_instruction_lines(project_instructions: ProjectInstructions) -> list[str]:
    lines = [
        "",
        "## Project Instructions",
        f"- project_instructions_path: {project_instructions.path}",
        f"- project_instructions_loaded: {str(project_instructions.loaded).lower()}",
        f"- project_instructions_chars: {project_instructions.char_count}",
        f"- project_instructions_truncated: {str(project_instructions.truncated).lower()}",
    ]
    if project_instructions.error:
        lines.append(f"- project_instructions_error: {project_instructions.error}")
    return lines


def _config_lines(config: AgentConfig) -> list[str]:
    return [
        "",
        "## Config",
        f"- config_mode: {config.mode}",
        f"- config_sandbox: {config.sandbox}",
        f"- config_approval: {config.approval}",
        f"- config_dry_run: {str(config.dry_run).lower()}",
    ]


def _final_from_observation(observation: Observation) -> str | None:
    data: dict[str, Any] | None = observation.data
    if not data:
        return None
    final = data.get("final")
    if final is None:
        return None
    return str(final)


def _changed_file_lines(observations: list[Observation]) -> list[str]:
    lines: list[str] = []
    for observation in observations:
        data = observation.data or {}
        snapshot_records = data.get("snapshots")
        if isinstance(snapshot_records, list):
            restore_hints = _restore_hints_by_path(data.get("restore_hints"))
            for snapshot in snapshot_records:
                if not isinstance(snapshot, dict):
                    continue
                path = snapshot.get("path")
                snapshot_path = snapshot.get("snapshot_path")
                if not path or not snapshot_path:
                    continue
                lines.append(f"- changed_file: {path}")
                lines.append(f"- snapshot: {snapshot_path}")
                restore_hint = restore_hints.get(str(path))
                if restore_hint:
                    lines.append(f"- restore: {restore_hint}")
            continue

        path = data.get("path")
        snapshot_path = data.get("snapshot_path")
        restore_hint = data.get("restore_hint")
        if not path or not snapshot_path:
            continue
        lines.append(f"- changed_file: {path}")
        lines.append(f"- snapshot: {snapshot_path}")
        if restore_hint:
            lines.append(f"- restore: {restore_hint}")
    return lines


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
