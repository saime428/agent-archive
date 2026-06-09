from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.core.actions import (
    ActionCall,
    ActionParseError,
    ErrorCode,
    InternalAction,
    Observation,
    make_error_observation,
    make_observation,
    parse_model_action,
)
from agent.core.budget import ContextBudget, truncate_observation, truncate_text
from agent.core.context import RunContext
from agent.core.hooks import run_hooks
from agent.core.memory import MemoryEntry, MemoryStore, build_memory_message
from agent.core.project_instructions import (
    ProjectInstructions,
    build_project_instructions_message,
    load_project_instructions,
)
from agent.core.redaction import redact_record, redact_value
from agent.core.skills import SkillError, SkillMetadata, build_skills_message, load_selected_skills
from agent.llm.base import LLMClient
from agent.policy.approvals import classify_action
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.filesystem import execute_tool
from agent.tools.documents import execute_document_tool
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
    skills: list[SkillMetadata]
    memory_entries: list[MemoryEntry]
    config: AgentConfig


@dataclass(frozen=True)
class TraceRecord:
    phase: str
    action_index: int
    observation_index: int
    repair_attempt: int | None
    terminal: bool
    policy_decision: str | None
    policy_reason: str | None
    config: dict[str, object]


SUPPORTED_TOOL_ACTIONS = {
    "list_dir",
    "read_file",
    "search_files",
    "write_file",
    "apply_patch",
    "run_command",
    "git_status",
    "git_diff",
    "read_pdf",
}
DRY_RUN_SKIPPED_ACTIONS = {
    "write_file",
    "apply_patch",
    "run_command",
}


def run_once(
    task: str,
    llm: LLMClient,
    *,
    cwd: Path | None = None,
    run_id: str | None = None,
    max_iterations: int = 3,
    config: AgentConfig | None = None,
    budget: ContextBudget | None = None,
    selected_skills: list[str] | tuple[str, ...] | None = None,
) -> RunResult:
    effective_config = config or AgentConfig()
    context = RunContext.create(task=task, cwd=cwd, run_id=run_id, budget=budget)
    run_dir = context.cwd / ".agent" / "runs" / context.run_id
    tool_calls_path = run_dir / "tool_calls.jsonl"
    summary_path = run_dir / "summary.md"
    hooks_path = run_dir / "hooks.jsonl"
    sandbox = WorkspaceSandbox(context.cwd)
    project_instructions = load_project_instructions(
        context.cwd,
        max_chars=context.budget.project_instructions_chars,
    )
    try:
        skills = load_selected_skills(
            context.cwd,
            selected_skills if selected_skills is not None else effective_config.default_skills,
            max_chars=context.budget.skill_body_chars,
        )
    except SkillError:
        skills = []
    memory_entries = MemoryStore(context.cwd).retrieve(
        task,
        max_items=effective_config.memory_max_items,
        max_chars=context.budget.memory_context_chars,
    )
    messages = _build_messages(task, project_instructions, skills, memory_entries)
    _run_hook_event("before_run", effective_config, hooks_path, {"run_id": context.run_id, "task": task})
    actions: list[InternalAction] = []
    observations: list[Observation] = []
    traces: list[TraceRecord] = []
    repair_attempt = 0
    model_call_index = 0
    completed_action_iterations = 0

    while completed_action_iterations < max_iterations:
        model_call_index += 1
        raw_response = llm.chat(messages)
        try:
            action = parse_model_action(
                raw_response,
                run_id=context.run_id,
                action_index=model_call_index,
                created_at=context.created_at,
            )
        except ActionParseError as exc:
            action, observation, trace = _parse_error_record(
                exc,
                raw_response,
                context,
                effective_config,
                action_index=model_call_index,
                observation_index=model_call_index,
                repair_attempt=repair_attempt,
            )
            observation = truncate_observation(observation, context.budget)
            actions.append(action)
            observations.append(observation)
            traces.append(trace)
            if not trace.terminal:
                messages.append(_build_repair_message(exc, raw_response, context, repair_attempt=repair_attempt))
                repair_attempt += 1
                continue
            break

        repair_attempt = 0
        completed_action_iterations += 1
        actions.append(action)

        before_tool_hooks = _run_hook_event(
            "before_tool",
            effective_config,
            hooks_path,
            {"run_id": context.run_id, "action": action.action.name},
        )
        if before_tool_hooks.blocking_error is not None:
            observation = make_error_observation(
                action.action_id,
                action.run_id,
                observation_index=model_call_index,
                code=ErrorCode.INTERNAL_ERROR,
                message=before_tool_hooks.blocking_error,
                details={"hook_event": "before_tool", "requested_action": action.action.name},
            )
            observation = truncate_observation(observation, context.budget)
            observations.append(observation)
            traces.append(
                TraceRecord(
                    phase="action",
                    action_index=model_call_index,
                    observation_index=model_call_index,
                    repair_attempt=None,
                    terminal=True,
                    **_trace_policy(action, effective_config),
                )
            )
            break

        if action.action.name == "done":
            observation = make_observation(
                action,
                observation_index=model_call_index,
                summary="Done.",
                data={"final": str(action.action.args["final"])},
            )
        elif action.action.name == "ask_user":
            observation = make_observation(
                action,
                observation_index=model_call_index,
                summary="User input requested.",
                data={
                    "question": str(action.action.args["question"]),
                    "options": list(action.action.args["options"]),
                    "reason": str(action.action.args["reason"]),
                },
            )
        elif action.action.name in SUPPORTED_TOOL_ACTIONS:
            observation = _tool_observation(
                action,
                context,
                sandbox,
                effective_config,
                observation_index=model_call_index,
            )
        else:
            observation = make_error_observation(
                action.action_id,
                action.run_id,
                observation_index=model_call_index,
                code=ErrorCode.POLICY_DENIED,
                message="This action is not supported in the current run loop.",
                details={"requested_action": action.action.name},
            )
        observation = truncate_observation(observation, context.budget)
        observations.append(observation)
        _run_hook_event(
            "after_tool",
            effective_config,
            hooks_path,
            {"run_id": context.run_id, "action": action.action.name, "status": observation.status},
        )
        traces.append(
            TraceRecord(
                phase="action",
                action_index=model_call_index,
                observation_index=model_call_index,
                repair_attempt=None,
                terminal=action.action.name in {"done", "ask_user"} or observation.status == "error",
                **_trace_policy(action, effective_config),
            )
        )
        if action.action.name in {"done", "ask_user"} or observation.status == "error":
            break
    else:
        action = actions[-1]
        observation = make_error_observation(
            action.action_id,
            context.run_id,
            observation_index=model_call_index + 1,
            code=ErrorCode.TOOL_FAILED,
            message="Run stopped after reaching the iteration limit.",
            details={"max_iterations": max_iterations},
        )
        observation = truncate_observation(observation, context.budget)
        observations.append(observation)

    _write_memory_candidate(context, observations)
    _run_hook_event(
        "after_run",
        effective_config,
        hooks_path,
        {"run_id": context.run_id, "status": observations[-1].status if observations else "unknown"},
    )
    _write_run_logs(
        context=context,
        actions=actions,
        observations=observations,
        traces=traces,
        project_instructions=project_instructions,
        skills=skills,
        memory_entries=memory_entries,
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
        skills=skills,
        memory_entries=memory_entries,
        config=effective_config,
    )


def _run_hook_event(event: str, config: AgentConfig, hooks_path: Path, payload: dict[str, Any]):
    return run_hooks(
        event=event,
        enabled_hooks=config.enabled_hooks,
        blocking_hooks=config.blocking_hooks,
        payload=payload,
        log_path=hooks_path,
    )


def _parse_error_record(
    exc: ActionParseError,
    raw_response: Any,
    context: RunContext,
    config: AgentConfig,
    *,
    action_index: int,
    observation_index: int,
    repair_attempt: int,
) -> tuple[InternalAction, Observation, TraceRecord]:
    raw_response_excerpt = _raw_response_excerpt(raw_response, context.budget)
    repairable = repair_attempt < context.budget.repair_attempts
    action = InternalAction(
        run_id=context.run_id,
        action_id=_format_action_id(action_index),
        created_at=context.created_at,
        message="Invalid model response.",
        action=ActionCall(
            name="invalid_model_response",
            args={"raw_response_excerpt": raw_response_excerpt},
        ),
    )
    observation = make_error_observation(
        action.action_id,
        context.run_id,
        observation_index=observation_index,
        code=exc.code,
        message=exc.message,
        details={
            "repair_attempt": repair_attempt,
            "max_repair_attempts": context.budget.repair_attempts,
            "repairable": repairable,
            "raw_response_excerpt": raw_response_excerpt,
        },
    )
    trace = TraceRecord(
        phase="parse",
        action_index=action_index,
        observation_index=observation_index,
        repair_attempt=repair_attempt,
        terminal=not repairable,
        policy_decision=None,
        policy_reason=None,
        config=_trace_config(config),
    )
    return action, observation, trace


def _build_repair_message(
    exc: ActionParseError,
    raw_response: Any,
    context: RunContext,
    *,
    repair_attempt: int,
) -> dict[str, str]:
    raw_response_excerpt = _raw_response_excerpt(raw_response, context.budget)
    return {
        "role": "user",
        "content": (
            "Your previous response could not be parsed as a valid JSON action.\n"
            f"Error code: {exc.code}\n"
            f"Error message: {exc.message}\n"
            f"Repair attempt: {repair_attempt + 1} of {context.budget.repair_attempts}\n"
            "Return exactly one valid JSON action object with top-level keys "
            '"message" and "action". Do not include markdown fences or extra text.\n'
            f"Previous response excerpt:\n{raw_response_excerpt}"
        ),
    }


def _raw_response_excerpt(raw_response: Any, budget: ContextBudget) -> str:
    text = _raw_response_text(raw_response)
    return truncate_text(text, budget.repair_excerpt_chars).value


def _raw_response_text(raw_response: Any) -> str:
    if isinstance(raw_response, str):
        return raw_response
    try:
        return json.dumps(raw_response, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError:
        return str(raw_response)


def _format_action_id(action_index: int) -> str:
    return f"act_{action_index:06d}"


def _tool_observation(
    action: InternalAction,
    context: RunContext,
    sandbox: WorkspaceSandbox,
    config: AgentConfig,
    *,
    observation_index: int,
) -> Observation:
    if config.dry_run and action.action.name in DRY_RUN_SKIPPED_ACTIONS:
        return make_observation(
            action,
            observation_index=observation_index,
            summary="Dry run skipped action.",
            data=_policy_details(action, config),
        )

    decision = classify_action(action, config)
    if decision.status == "approval_required":
        return make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=observation_index,
            code=ErrorCode.APPROVAL_REQUIRED,
            message=decision.reason,
            details=_policy_details(action, config),
        )
    if decision.status == "deny":
        return make_error_observation(
            action.action_id,
            action.run_id,
            observation_index=observation_index,
            code=ErrorCode.POLICY_DENIED,
            message=decision.reason,
            details=_policy_details(action, config),
        )

    if action.action.name in {
        "list_dir",
        "read_file",
        "search_files",
        "write_file",
        "apply_patch",
    }:
        return execute_tool(
            action,
            context,
            sandbox,
            observation_index=observation_index,
        )
    if action.action.name == "run_command":
        return execute_run_command(
            action,
            context,
            sandbox,
            observation_index=observation_index,
        )
    if action.action.name in {"git_status", "git_diff"}:
        return execute_git_tool(
            action,
            context,
            sandbox,
            observation_index=observation_index,
        )
    if action.action.name == "read_pdf":
        return execute_document_tool(
            action,
            context,
            sandbox,
            observation_index=observation_index,
        )

    return make_error_observation(
        action.action_id,
        action.run_id,
        observation_index=observation_index,
        code=ErrorCode.POLICY_DENIED,
        message="This action is not supported in the current run loop.",
        details={"requested_action": action.action.name},
    )


def _policy_details(action: InternalAction, config: AgentConfig) -> dict[str, object]:
    return {
        "requested_action": action.action.name,
        "approval": config.approval,
        "dry_run": config.dry_run,
    }


def _trace_policy(action: InternalAction, config: AgentConfig) -> dict[str, object]:
    if config.dry_run and action.action.name in DRY_RUN_SKIPPED_ACTIONS:
        return {
            "policy_decision": "dry_run_skipped",
            "policy_reason": "Dry run skipped action.",
            "config": _trace_config(config),
        }

    decision = classify_action(action, config)
    return {
        "policy_decision": decision.status,
        "policy_reason": decision.reason,
        "config": _trace_config(config),
    }


def _trace_config(config: AgentConfig) -> dict[str, object]:
    return {
        "provider": config.provider,
        "model": config.model,
        "default_skills": list(config.default_skills),
        "memory_auto_write": config.memory_auto_write,
        "memory_max_items": config.memory_max_items,
        "enabled_hooks": list(config.enabled_hooks),
        "blocking_hooks": list(config.blocking_hooks),
        "mode": config.mode,
        "sandbox": config.sandbox,
        "approval": config.approval,
        "dry_run": config.dry_run,
    }


def _build_messages(
    task: str,
    project_instructions: ProjectInstructions,
    skills: list[SkillMetadata],
    memory_entries: list[MemoryEntry],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    project_message = build_project_instructions_message(project_instructions)
    if project_message is not None:
        messages.append(project_message)
    skill_message = build_skills_message(skills)
    if skill_message is not None:
        messages.append(skill_message)
    memory_message = build_memory_message(memory_entries)
    if memory_message is not None:
        messages.append(memory_message)
    messages.append({"role": "user", "content": task})
    return messages


def _write_memory_candidate(context: RunContext, observations: list[Observation]) -> None:
    if not observations:
        return
    observation = observations[-1]
    if observation.status != "ok":
        return
    final = _final_from_observation(observation)
    if not final:
        return
    MemoryStore(context.cwd).add_candidate(source_run_id=context.run_id, source_excerpt=final)


def _write_run_logs(
    *,
    context: RunContext,
    actions: list[InternalAction],
    observations: list[Observation],
    traces: list[TraceRecord],
    project_instructions: ProjectInstructions,
    skills: list[SkillMetadata],
    memory_entries: list[MemoryEntry],
    config: AgentConfig,
    tool_calls_path: Path,
    summary_path: Path,
) -> None:
    tool_calls_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    redaction_replacements = 0
    for index, (action, observation) in enumerate(zip(actions, observations, strict=False)):
        record = {
            "action": action.model_dump(mode="json"),
            "observation": observation.model_dump(mode="json"),
        }
        if index < len(traces):
            record["trace"] = {
                "phase": traces[index].phase,
                "action_index": traces[index].action_index,
                "observation_index": traces[index].observation_index,
                "repair_attempt": traces[index].repair_attempt,
                "terminal": traces[index].terminal,
                "policy_decision": traces[index].policy_decision,
                "policy_reason": traces[index].policy_reason,
                "config": traces[index].config,
            }
        redacted_record = redact_record(record)
        redaction_replacements += redacted_record.replacements
        serialized_record = redacted_record.value
        if redacted_record.applied:
            serialized_record["redaction"] = {
                "applied": True,
                "replacements": redacted_record.replacements,
            }
        records.append(
            json.dumps(
                serialized_record,
                ensure_ascii=True,
            )
        )
    tool_calls_path.write_text(
        "\n".join(records) + "\n",
        encoding="utf-8",
    )
    summary = _render_summary(context, actions, observations, project_instructions, skills, memory_entries, config)
    redacted_summary = redact_value(summary)
    redaction_replacements += redacted_summary.replacements
    summary_text = redacted_summary.value
    if redaction_replacements:
        summary_text = summary_text.rstrip("\n") + "\n- redaction_applied: true\n"
    summary_path.write_text(summary_text, encoding="utf-8")


def _render_summary(
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
        f"- config_memory_auto_write: {str(config.memory_auto_write).lower()}",
        f"- config_memory_max_items: {config.memory_max_items}",
        f"- config_enabled_hooks: {list(config.enabled_hooks)}",
        f"- config_blocking_hooks: {list(config.blocking_hooks)}",
        f"- config_mode: {config.mode}",
        f"- config_sandbox: {config.sandbox}",
        f"- config_approval: {config.approval}",
        f"- config_dry_run: {str(config.dry_run).lower()}",
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
