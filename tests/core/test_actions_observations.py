from __future__ import annotations

from datetime import datetime, timezone

from agent.core.actions import ErrorCode, make_error_observation, make_observation, parse_model_action


CREATED_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_make_observation_matches_action_ids() -> None:
    action = parse_model_action(
        {
            "message": "Ask.",
            "action": {
                "name": "ask_user",
                "args": {
                    "question": "Proceed?",
                    "options": ["yes", "no"],
                    "reason": "Need confirmation.",
                },
            },
        },
        run_id="run_123",
        action_index=2,
        created_at=CREATED_AT,
    )

    observation = make_observation(
        action,
        observation_index=3,
        summary="Asked user.",
        data={"question": "Proceed?"},
    )

    assert observation.protocol_version == "agent-observation-v1"
    assert observation.run_id == "run_123"
    assert observation.action_id == "act_000002"
    assert observation.observation_id == "obs_000003"
    assert observation.status == "ok"
    assert observation.error is None
    assert observation.data == {"question": "Proceed?"}


def test_make_error_observation_uses_standard_error_shape() -> None:
    observation = make_error_observation(
        "act_000004",
        "run_123",
        observation_index=5,
        code=ErrorCode.UNKNOWN_TOOL,
        message="Unknown tool.",
        details={"tool": "future_tool"},
    )

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.UNKNOWN_TOOL
    assert observation.error.message == "Unknown tool."
    assert observation.error.details == {"tool": "future_tool"}
    assert observation.summary == "Unknown tool."


def test_recoverable_error_codes_classification() -> None:
    from agent.core.actions import RECOVERABLE_ERROR_CODES

    assert ErrorCode.TOOL_FAILED in RECOVERABLE_ERROR_CODES
    assert ErrorCode.TIMEOUT in RECOVERABLE_ERROR_CODES
    assert ErrorCode.SANDBOX_VIOLATION in RECOVERABLE_ERROR_CODES
    assert ErrorCode.INVALID_ARGUMENT in RECOVERABLE_ERROR_CODES
    assert ErrorCode.POLICY_DENIED in RECOVERABLE_ERROR_CODES
    assert ErrorCode.APPROVAL_DENIED not in RECOVERABLE_ERROR_CODES
    assert ErrorCode.APPROVAL_REQUIRED not in RECOVERABLE_ERROR_CODES
    assert ErrorCode.INTERNAL_ERROR not in RECOVERABLE_ERROR_CODES

