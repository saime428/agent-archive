from __future__ import annotations

from agent.core.actions import make_observation, parse_model_action
from agent.core.budget import ContextBudget, TRUNCATION_MARKER, truncate_observation, truncate_text
from agent.core.context import RunContext


def test_context_budget_defaults_match_existing_limits() -> None:
    budget = ContextBudget()

    assert budget.project_instructions_chars == 8_000
    assert budget.file_read_max_lines == 200
    assert budget.file_read_max_chars == 20_000
    assert budget.search_max_matches == 50
    assert budget.search_excerpt_chars == 200
    assert budget.command_output_chars == 20_000
    assert budget.git_output_chars == 20_000
    assert budget.observation_data_chars == 20_000
    assert budget.observation_summary_chars == 1_000


def test_truncate_text_leaves_short_text_unchanged() -> None:
    result = truncate_text("hello", 10)

    assert result.value == "hello"
    assert result.truncated is False


def test_truncate_text_appends_marker_to_long_text() -> None:
    result = truncate_text("abcdef", 3)

    assert result.value == f"abc{TRUNCATION_MARKER}"
    assert result.truncated is True


def test_truncate_observation_marks_summary_and_data_truncation() -> None:
    context = RunContext.create("budget", run_id="run_budget")
    action = parse_model_action(
        {
            "message": "Done.",
            "action": {
                "name": "done",
                "args": {"final": "ok", "changed_files": [], "next_steps": []},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )
    observation = make_observation(
        action,
        observation_index=1,
        summary="summary is too long",
        data={"content": "x" * 200},
    )

    truncated = truncate_observation(
        observation,
        ContextBudget(observation_summary_chars=7, observation_data_chars=40),
    )

    assert truncated.summary == f"summary{TRUNCATION_MARKER}"
    assert truncated.data is not None
    assert truncated.data["budget_truncated"] is True
    assert truncated.data["data_excerpt"].endswith(TRUNCATION_MARKER)
