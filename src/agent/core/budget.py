from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.core.actions import Observation


TRUNCATION_MARKER = "\n[truncated]"


@dataclass(frozen=True)
class ContextBudget:
    project_instructions_chars: int = 8_000
    file_read_max_lines: int = 200
    file_read_max_chars: int = 20_000
    search_max_matches: int = 50
    search_excerpt_chars: int = 200
    command_output_chars: int = 20_000
    git_output_chars: int = 20_000
    observation_data_chars: int = 20_000
    observation_summary_chars: int = 1_000


@dataclass(frozen=True)
class TruncationResult:
    value: str
    truncated: bool


def truncate_text(text: str, max_chars: int) -> TruncationResult:
    if len(text) <= max_chars:
        return TruncationResult(text, False)
    return TruncationResult(text[: max(max_chars, 0)] + TRUNCATION_MARKER, True)


def truncate_observation(observation: Observation, budget: ContextBudget) -> Observation:
    summary = truncate_text(observation.summary, budget.observation_summary_chars)
    data, data_truncated = _truncate_data(observation.data, budget.observation_data_chars)
    was_truncated = summary.truncated or data_truncated
    if was_truncated:
        data = _mark_budget_truncated(data)
    return observation.model_copy(
        update={
            "summary": summary.value,
            "data": data,
        }
    )


def _truncate_data(data: dict[str, Any] | None, max_chars: int) -> tuple[dict[str, Any] | None, bool]:
    if data is None:
        return None, False

    serialized = json.dumps(data, ensure_ascii=True, sort_keys=True, default=str)
    if len(serialized) <= max_chars:
        return dict(data), False

    excerpt = truncate_text(serialized, max_chars).value
    return {"data_excerpt": excerpt}, True


def _mark_budget_truncated(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {"budget_truncated": True}
    marked = dict(data)
    marked["budget_truncated"] = True
    return marked
