from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.core.actions import (
    ActionParseError,
    ErrorCode,
    make_error_observation,
    make_observation,
    parse_model_action,
)


CREATED_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_model_action_injects_core_metadata() -> None:
    action = parse_model_action(
        {
            "message": "Inspect the project.",
            "action": {
                "name": "list_dir",
                "args": {"path": ".", "max_entries": 20},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.protocol_version == "agent-action-v1"
    assert action.run_id == "run_123"
    assert action.action_id == "act_000001"
    assert action.created_at == CREATED_AT
    assert action.message == "Inspect the project."
    assert action.action.name == "list_dir"
    assert action.action.args == {"path": ".", "max_entries": 20}


def test_parse_model_action_overwrites_model_metadata() -> None:
    action = parse_model_action(
        {
            "protocol_version": "fake",
            "run_id": "model_run",
            "action_id": "model_action",
            "created_at": "1999-01-01T00:00:00Z",
            "message": "Finish.",
            "action": {
                "name": "done",
                "args": {
                    "final": "Complete.",
                    "changed_files": [],
                    "next_steps": [],
                },
            },
        },
        run_id="core_run",
        action_index=7,
        created_at=CREATED_AT,
    )

    assert action.protocol_version == "agent-action-v1"
    assert action.run_id == "core_run"
    assert action.action_id == "act_000007"
    assert action.created_at == CREATED_AT


def test_parse_model_action_rejects_invalid_json() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            "{not-json",
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_JSON


def test_parse_model_action_rejects_unknown_tool() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Use a future tool.",
                "action": {"name": "future_tool", "args": {}},
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.UNKNOWN_TOOL


def test_parse_model_action_rejects_missing_required_field() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {"message": "Missing action."},
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.MISSING_REQUIRED_FIELD


def test_parse_model_action_rejects_extra_fields() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read file.",
                "action": {
                    "name": "read_file",
                    "args": {
                        "path": "pyproject.toml",
                        "start_line": None,
                        "max_lines": None,
                        "surprise": True,
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_search_files_args() -> None:
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "*.py", "path": ".", "max_matches": 10},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "search_files"
    assert action.action.args == {"query": "*.py", "path": ".", "max_matches": 10}


def test_parse_model_action_rejects_extra_search_files_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Search.",
                "action": {
                    "name": "search_files",
                    "args": {"query": "*.py", "unexpected": True},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_write_file_args() -> None:
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": "notes.txt",
                    "content": "hello\n",
                    "create_parents": False,
                },
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "write_file"
    assert action.action.args == {
        "path": "notes.txt",
        "content": "hello\n",
        "create_parents": False,
    }


def test_parse_model_action_requires_write_file_content() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "notes.txt", "create_parents": False},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.MISSING_REQUIRED_FIELD


def test_parse_model_action_rejects_extra_write_file_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {
                        "path": "notes.txt",
                        "content": "hello\n",
                        "create_parents": False,
                        "mode": "append",
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_apply_patch_args_with_default_occurrence() -> None:
    action = parse_model_action(
        {
            "message": "Patch.",
            "action": {
                "name": "apply_patch",
                "args": {
                    "edits": [
                        {
                            "path": "notes.txt",
                            "old": "hello",
                            "new": "hi",
                        }
                    ]
                },
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "apply_patch"
    assert action.action.args == {
        "edits": [
            {
                "path": "notes.txt",
                "old": "hello",
                "new": "hi",
                "occurrence": "first",
            }
        ]
    }


def test_parse_model_action_requires_apply_patch_edits() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Patch.",
                "action": {"name": "apply_patch", "args": {}},
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.MISSING_REQUIRED_FIELD


def test_parse_model_action_rejects_empty_apply_patch_edits() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Patch.",
                "action": {"name": "apply_patch", "args": {"edits": []}},
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_empty_apply_patch_path_and_old() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Patch.",
                "action": {
                    "name": "apply_patch",
                    "args": {
                        "edits": [
                            {
                                "path": "",
                                "old": "",
                                "new": "hi",
                                "occurrence": "first",
                            }
                        ]
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_apply_patch_edit_fields() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Patch.",
                "action": {
                    "name": "apply_patch",
                    "args": {
                        "edits": [
                            {
                                "path": "notes.txt",
                                "old": "hello",
                                "new": "hi",
                                "occurrence": "first",
                                "mode": "append",
                            }
                        ]
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_invalid_apply_patch_occurrence() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Patch.",
                "action": {
                    "name": "apply_patch",
                    "args": {
                        "edits": [
                            {
                                "path": "notes.txt",
                                "old": "hello",
                                "new": "hi",
                                "occurrence": "last",
                            }
                        ]
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_run_command_args() -> None:
    action = parse_model_action(
        {
            "message": "Run tests.",
            "action": {
                "name": "run_command",
                "args": {
                    "argv": ["pytest", "-q"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                },
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "run_command"
    assert action.action.args == {
        "argv": ["pytest", "-q"],
        "cwd": ".",
        "timeout_seconds": 10,
    }


def test_parse_model_action_rejects_empty_run_command_argv() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Run nothing.",
                "action": {
                    "name": "run_command",
                    "args": {"argv": [], "cwd": None, "timeout_seconds": None},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_run_command_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Run tests.",
                "action": {
                    "name": "run_command",
                    "args": {
                        "argv": ["pytest"],
                        "cwd": None,
                        "timeout_seconds": None,
                        "shell": True,
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


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
