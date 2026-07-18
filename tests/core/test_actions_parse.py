from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from agent.core.actions import (
    ActionParseError,
    ErrorCode,
    make_error_observation,
    make_observation,
    parse_model_action,
)
from agent.core.tool_catalog import build_tool_catalog
from agent.mcp_runtime import McpToolDefinition, McpToolTarget


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


def test_parse_model_action_accepts_read_file_file_path_alias() -> None:
    action = parse_model_action(
        {
            "message": "Read file.",
            "action": {
                "name": "read_file",
                "args": {"file_path": "pyproject.toml"},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "read_file"
    assert action.action.args == {"path": "pyproject.toml", "start_line": None, "max_lines": None}


def test_parse_model_action_accepts_minimal_ask_user_args() -> None:
    action = parse_model_action(
        {
            "message": "Ask.",
            "action": {
                "name": "ask_user",
                "args": {"question": "Please describe the task."},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "ask_user"
    assert action.action.args == {
        "question": "Please describe the task.",
        "options": [],
        "reason": "The model requested more information.",
    }


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


def test_parse_model_action_accepts_web_search_args() -> None:
    action = parse_model_action(
        {
            "message": "Search web.",
            "action": {
                "name": "web_search",
                "args": {"query": "codex news", "max_results": 3},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "web_search"
    assert action.action.args == {"query": "codex news", "max_results": 3}


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


def test_parse_model_action_accepts_git_status_args() -> None:
    action = parse_model_action(
        {
            "message": "Check status.",
            "action": {
                "name": "git_status",
                "args": {"short": True},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "git_status"
    assert action.action.args == {"short": True}


def test_parse_model_action_rejects_extra_git_status_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Check status.",
                "action": {
                    "name": "git_status",
                    "args": {"short": True, "porcelain": True},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_git_diff_args() -> None:
    action = parse_model_action(
        {
            "message": "Check diff.",
            "action": {
                "name": "git_diff",
                "args": {"path": None, "cached": False, "max_bytes": 1000},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "git_diff"
    assert action.action.args == {"path": None, "cached": False, "max_bytes": 1000}


def test_parse_model_action_accepts_read_pdf_args() -> None:
    action = parse_model_action(
        {
            "message": "Read PDF.",
            "action": {
                "name": "read_pdf",
                "args": {"path": "docs/main.pdf", "max_chars": 4000},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "read_pdf"
    assert action.action.args == {"path": "docs/main.pdf", "max_chars": 4000}


def test_parse_model_action_rejects_invalid_read_pdf_max_chars() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read PDF.",
                "action": {
                    "name": "read_pdf",
                    "args": {"path": "docs/main.pdf", "max_chars": 0},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_read_docx_args() -> None:
    action = parse_model_action(
        {
            "message": "Read DOCX.",
            "action": {
                "name": "read_docx",
                "args": {"path": "docs/interview.docx", "max_chars": 4000},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "read_docx"
    assert action.action.args == {"path": "docs/interview.docx", "max_chars": 4000}


def test_parse_model_action_rejects_empty_read_docx_path() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read DOCX.",
                "action": {
                    "name": "read_docx",
                    "args": {"path": "  ", "max_chars": None},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_invalid_read_docx_max_chars() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read DOCX.",
                "action": {
                    "name": "read_docx",
                    "args": {"path": "docs/interview.docx", "max_chars": 0},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_read_docx_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read DOCX.",
                "action": {
                    "name": "read_docx",
                    "args": {"path": "docs/interview.docx", "max_chars": None, "comments": True},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_read_xlsx_args() -> None:
    action = parse_model_action(
        {
            "message": "Read XLSX.",
            "action": {
                "name": "read_xlsx",
                "args": {"path": "docs/data.xlsx", "max_chars": 4000},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "read_xlsx"
    assert action.action.args == {"path": "docs/data.xlsx", "max_chars": 4000}


def test_parse_model_action_rejects_empty_read_xlsx_path() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read XLSX.",
                "action": {
                    "name": "read_xlsx",
                    "args": {"path": "  ", "max_chars": None},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_invalid_read_xlsx_max_chars() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read XLSX.",
                "action": {
                    "name": "read_xlsx",
                    "args": {"path": "docs/data.xlsx", "max_chars": 0},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_read_xlsx_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read XLSX.",
                "action": {
                    "name": "read_xlsx",
                    "args": {"path": "docs/data.xlsx", "max_chars": None, "formulas": True},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_read_pptx_args() -> None:
    action = parse_model_action(
        {
            "message": "Read PPTX.",
            "action": {
                "name": "read_pptx",
                "args": {"path": "docs/slides.pptx", "max_chars": 4000},
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "read_pptx"
    assert action.action.args == {"path": "docs/slides.pptx", "max_chars": 4000}


def test_parse_model_action_rejects_empty_read_pptx_path() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read PPTX.",
                "action": {
                    "name": "read_pptx",
                    "args": {"path": "  ", "max_chars": None},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_invalid_read_pptx_max_chars() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read PPTX.",
                "action": {
                    "name": "read_pptx",
                    "args": {"path": "docs/slides.pptx", "max_chars": 0},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_read_pptx_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Read PPTX.",
                "action": {
                    "name": "read_pptx",
                    "args": {"path": "docs/slides.pptx", "max_chars": None, "notes": True},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_accepts_write_markdown_report_args() -> None:
    action = parse_model_action(
        {
            "message": "Write report.",
            "action": {
                "name": "write_markdown_report",
                "args": {
                    "path": "reports/summary.md",
                    "title": "Research Summary",
                    "body": "Findings from the source material.",
                    "sources": ["docs/main.pdf"],
                    "create_parents": True,
                },
            },
        },
        run_id="run_123",
        action_index=1,
        created_at=CREATED_AT,
    )

    assert action.action.name == "write_markdown_report"
    assert action.action.args == {
        "path": "reports/summary.md",
        "title": "Research Summary",
        "body": "Findings from the source material.",
        "sources": ["docs/main.pdf"],
        "create_parents": True,
    }


def test_parse_model_action_rejects_empty_write_markdown_report_fields() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Write report.",
                "action": {
                    "name": "write_markdown_report",
                    "args": {
                        "path": " ",
                        "title": "Research Summary",
                        "body": "Findings.",
                        "sources": ["docs/main.pdf"],
                        "create_parents": False,
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_empty_write_markdown_report_sources() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Write report.",
                "action": {
                    "name": "write_markdown_report",
                    "args": {
                        "path": "reports/summary.md",
                        "title": "Research Summary",
                        "body": "Findings.",
                        "sources": [],
                        "create_parents": False,
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_write_markdown_report_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Write report.",
                "action": {
                    "name": "write_markdown_report",
                    "args": {
                        "path": "reports/summary.md",
                        "title": "Research Summary",
                        "body": "Findings.",
                        "sources": ["docs/main.pdf"],
                        "create_parents": False,
                        "format": "pdf",
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_invalid_git_diff_max_bytes() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Check diff.",
                "action": {
                    "name": "git_diff",
                    "args": {"path": None, "cached": False, "max_bytes": 0},
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT


def test_parse_model_action_rejects_extra_git_diff_args() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Check diff.",
                "action": {
                    "name": "git_diff",
                    "args": {
                        "path": None,
                        "cached": False,
                        "max_bytes": None,
                        "stat": True,
                    },
                },
            },
            run_id="run_123",
            action_index=1,
            created_at=CREATED_AT,
        )

    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT



def _dynamic_tool_catalog():
    schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    runtime_definition = McpToolDefinition(
        exposed_name="mcp__local__echo",
        target=McpToolTarget(
            server_id="local",
            remote_name="echo",
            snapshot_contract=SimpleNamespace(output_validator=None),
        ),
        description="Echo a message.",
        input_schema=dict(schema),
        output_schema=None,
        input_validator=Draft202012Validator(dict(schema)),
    )
    return build_tool_catalog((runtime_definition,))


def test_parse_model_action_accepts_dynamic_catalog_tool() -> None:
    action = parse_model_action(
        {
            "message": "Call echo.",
            "action": {
                "name": "mcp__local__echo",
                "args": {"message": "hello"},
            },
        },
        run_id="run_dynamic",
        action_index=1,
        created_at=CREATED_AT,
        tool_catalog=_dynamic_tool_catalog(),
    )

    assert action.action.name == "mcp__local__echo"
    assert action.action.args == {"message": "hello"}


@pytest.mark.parametrize(
    "args, expected_code",
    [
        ({}, ErrorCode.MISSING_REQUIRED_FIELD),
        ({"message": 1}, ErrorCode.INVALID_ARGUMENT),
        ({"message": "ok", "extra": True}, ErrorCode.INVALID_ARGUMENT),
    ],
)
def test_parse_model_action_rejects_invalid_dynamic_args(args, expected_code) -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Call echo.",
                "action": {"name": "mcp__local__echo", "args": args},
            },
            run_id="run_dynamic",
            action_index=1,
            created_at=CREATED_AT,
            tool_catalog=_dynamic_tool_catalog(),
        )

    assert exc_info.value.code == expected_code


def test_parse_model_action_rejects_dynamic_tool_absent_from_catalog() -> None:
    with pytest.raises(ActionParseError) as exc_info:
        parse_model_action(
            {
                "message": "Call unknown.",
                "action": {"name": "mcp__local__missing", "args": {}},
            },
            run_id="run_dynamic",
            action_index=1,
            created_at=CREATED_AT,
            tool_catalog=_dynamic_tool_catalog(),
        )

    assert exc_info.value.code == ErrorCode.UNKNOWN_TOOL
