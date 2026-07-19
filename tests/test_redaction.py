from __future__ import annotations

from agent.core.actions import ErrorCode, make_error_observation
from agent.core.redaction import REDACTED, redact_observation, redact_record, redact_value


def test_redact_record_replaces_sensitive_keys() -> None:
    result = redact_record(
        {
            "api_key": "sk-test-secret-123456",
            "password": "correct horse battery staple",
            "authorization": "Bearer abc.def.ghi",
            "safe": "hello",
        }
    )

    assert result.value == {
        "api_key": REDACTED,
        "password": REDACTED,
        "authorization": REDACTED,
        "safe": "hello",
    }
    assert result.applied is True
    assert result.replacements == 3


def test_redact_value_replaces_secret_like_string_fragments() -> None:
    result = redact_value(
        "use sk-test-secret-123456 and Authorization: Bearer abc.def.ghi"
    )

    assert result.value == f"use {REDACTED} and {REDACTED}"
    assert result.applied is True
    assert result.replacements == 2


def test_redact_record_recurses_into_nested_values() -> None:
    result = redact_record(
        {
            "outer": [
                {"token": "plain-token-value"},
                {"message": "AWS key AKIA1234567890ABCDEF found"},
                {"private_key": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"},
            ]
        }
    )

    assert result.value == {
        "outer": [
            {"token": REDACTED},
            {"message": f"AWS key {REDACTED} found"},
            {"private_key": REDACTED},
        ]
    }
    assert result.replacements == 3


def test_redact_value_leaves_ordinary_text_paths_and_diffs_unchanged() -> None:
    ordinary = (
        "diff --git a/src/app.py b/src/app.py\n"
        "+print('hello from F:/agent/src/app.py')\n"
        "Bearerish text without credentials\n"
    )

    result = redact_value(ordinary)

    assert result.value == ordinary
    assert result.applied is False
    assert result.replacements == 0


def test_redact_record_does_not_redact_non_secret_token_budget_keys() -> None:
    result = redact_record({"max_tokens": 20_000, "token_budget": 1_000})

    assert result.value == {"max_tokens": 20_000, "token_budget": 1_000}
    assert result.applied is False


def test_redact_observation_returns_a_redacted_copy_and_count() -> None:
    secret = "sk-test-secret-123456"
    observation = make_error_observation(
        "act_000001",
        "run_secret",
        observation_index=1,
        code=ErrorCode.TOOL_FAILED,
        message=f"Failed with {secret}.",
        details={"token": "plain-token-value"},
    ).model_copy(update={"data": {"nested": f"Value: {secret}"}})

    result = redact_observation(observation)

    assert result.value.summary == "Failed with [REDACTED]."
    assert result.value.error is not None
    assert result.value.error.message == "Failed with [REDACTED]."
    assert result.value.error.details == {"token": REDACTED}
    assert result.value.data == {"nested": "Value: [REDACTED]"}
    assert result.replacements == 4
    assert result.value.run_id == observation.run_id
    assert result.value.observation_id == observation.observation_id
    assert secret in observation.summary
