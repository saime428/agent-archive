from __future__ import annotations

from typing import Any

from agent.config import AgentConfig
from agent.core.actions import ErrorCode, InternalAction, Observation
from agent.core.context import RunContext
from agent.core.memory import MemoryEntry
from agent.core.project_instructions import ProjectInstructions
from agent.core.skills import SkillMetadata


def render_summary(
    context: RunContext,
    actions: list[InternalAction],
    observations: list[Observation],
    project_instructions: ProjectInstructions,
    skills: list[SkillMetadata],
    memory_entries: list[MemoryEntry],
    config: AgentConfig,
) -> str:
    action = actions[-1]
    observation = observations[-1]
    terminal_reason = _terminal_reason(action, observation)
    lines = [
        f"# Run {context.run_id}",
        "",
        f"- task: {context.task}",
        f"- action: {action.action.name}",
        f"- status: {observation.status}",
        f"- completed: {str(_completed(action, observation)).lower()}",
        f"- terminal_reason: {terminal_reason}",
        f"- last_action: {action.action.name}",
        f"- last_observation_summary: {observation.summary}",
    ]
    final = final_from_observation(observation)
    if final:
        lines.append(f"- final: {final}")
    if observation.error:
        lines.append(f"- error: {observation.error.code}: {observation.error.message}")
    failure_explanation = _failure_explanation(action, observation, terminal_reason)
    if failure_explanation:
        lines.append(f"- failure_explanation: {failure_explanation}")
    if action.action.name == "ask_user":
        lines.extend(_ask_user_lines(observation))
    lines.extend(_project_instruction_lines(project_instructions))
    lines.extend(_skill_lines(skills))
    lines.extend(_memory_lines(memory_entries))
    lines.extend(_config_lines(config))
    changed_lines = _changed_file_lines(observations)
    if changed_lines:
        lines.extend(["", "## Changes", *changed_lines])
    lines.append("")
    return "\n".join(lines)


def final_from_observation(observation: Observation) -> str | None:
    data: dict[str, Any] | None = observation.data
    if not data:
        return None
    final = data.get("final")
    if final is None:
        return None
    return str(final)


def restore_hints_by_path(raw_restore_hints: Any) -> dict[str, str]:
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


def _completed(action: InternalAction, observation: Observation) -> bool:
    return action.action.name == "done" and observation.status == "ok"


def _terminal_reason(action: InternalAction, observation: Observation) -> str:
    if _completed(action, observation):
        return "done"
    if action.action.name == "ask_user" and observation.status == "ok":
        return "ask_user"
    if _is_iteration_limit(observation):
        return "iteration_limit"
    if observation.error is not None and observation.error.code == ErrorCode.CANCELLED:
        return "cancelled"
    if (
        observation.error is not None
        and observation.error.code == ErrorCode.TIMEOUT
        and (observation.error.details or {}).get("stop_reason") == "timed_out"
    ):
        return "timed_out"
    if observation.error is not None:
        return f"error:{observation.error.code}"
    return "stopped"


def _failure_explanation(action: InternalAction, observation: Observation, terminal_reason: str) -> str | None:
    if terminal_reason == "iteration_limit":
        return f"The model did not return done before the iteration limit; last action was {action.action.name}."
    if observation.error is not None:
        return observation.error.message
    return None


def _is_iteration_limit(observation: Observation) -> bool:
    if observation.error is None:
        return False
    return (
        observation.error.code == ErrorCode.TOOL_FAILED
        and observation.error.message == "Run stopped after reaching the iteration limit."
    )


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


def _skill_lines(skills: list[SkillMetadata]) -> list[str]:
    lines = ["", "## Skills", f"- skills_loaded: {len(skills)}"]
    for skill in skills:
        lines.append(f"- skill: {skill.name}")
        lines.append(f"  source: {skill.source}")
        lines.append(f"  truncated: {str(skill.truncated).lower()}")
    return lines


def _memory_lines(memory_entries: list[MemoryEntry]) -> list[str]:
    lines = ["", "## Memory", f"- memory_loaded: {len(memory_entries)}"]
    for entry in memory_entries:
        lines.append(f"- memory_entry: {entry.entry_id}")
        lines.append(f"  source_run_id: {entry.source_run_id}")
    return lines


def _config_lines(config: AgentConfig) -> list[str]:
    return [
        "",
        "## Config",
        f"- config_provider: {config.provider}",
        f"- config_model: {config.model}",
        f"- config_deepseek_api_key_env: {config.deepseek_api_key_env}",
        f"- config_default_skills: {list(config.default_skills)}",
        f"- config_allowed_commands: {list(config.allowed_commands)}",
        f"- config_memory_auto_write: {str(config.memory_auto_write).lower()}",
        f"- config_memory_max_items: {config.memory_max_items}",
        f"- config_enabled_hooks: {list(config.enabled_hooks)}",
        f"- config_blocking_hooks: {list(config.blocking_hooks)}",
        f"- config_mode: {config.mode}",
        f"- config_sandbox: {config.sandbox}",
        f"- config_approval: {config.approval}",
        f"- config_dry_run: {str(config.dry_run).lower()}",
        f"- config_web_search_enabled: {str(config.web_search_enabled).lower()}",
        f"- config_computer_read_enabled: {str(config.computer_read_enabled).lower()}",
    ]


def _ask_user_lines(observation: Observation) -> list[str]:
    data = observation.data or {}
    lines = ["", "## User Input Request"]
    if data.get("question") is not None:
        lines.append(f"- question: {data['question']}")
    if data.get("options") is not None:
        lines.append(f"- options: {data['options']}")
    if data.get("reason") is not None:
        lines.append(f"- reason: {data['reason']}")
    return lines


def _changed_file_lines(observations: list[Observation]) -> list[str]:
    lines: list[str] = []
    for observation in observations:
        data = observation.data or {}
        snapshot_records = data.get("snapshots")
        if isinstance(snapshot_records, list):
            restore_hints = restore_hints_by_path(data.get("restore_hints"))
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
