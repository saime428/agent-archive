from agent.core.actions import ErrorCode, make_error_observation, parse_model_action
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.filesystem import execute_tool


def test_list_dir_returns_entries_and_truncation(tmp_path) -> None:
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a").mkdir()
    context = RunContext.create("inspect", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "List.",
            "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 1}},
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["total_entries"] == 2
    assert observation.data["truncated"] is True
    assert len(observation.data["entries"]) == 1
    assert observation.data["entries"][0]["type"] in {"file", "directory"}


def test_read_file_returns_text_and_line_metadata(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    context = RunContext.create("read", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Read.",
            "action": {
                "name": "read_file",
                "args": {"path": "notes.txt", "start_line": 2, "max_lines": 1},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["content"] == "two"
    assert observation.data["start_line"] == 2
    assert observation.data["end_line"] == 2
    assert observation.data["truncated"] is False


def test_read_file_rejects_binary_file(tmp_path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02")
    context = RunContext.create("read", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Read.",
            "action": {
                "name": "read_file",
                "args": {"path": "image.bin", "start_line": None, "max_lines": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED


def test_read_file_truncates_large_file(tmp_path) -> None:
    (tmp_path / "large.txt").write_text("\n".join(str(i) for i in range(300)), encoding="utf-8")
    context = RunContext.create("read", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Read.",
            "action": {
                "name": "read_file",
                "args": {"path": "large.txt", "start_line": None, "max_lines": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["truncated"] is True
    assert "[truncated]" in observation.data["content"]


def test_execute_tool_returns_sandbox_error_observation(tmp_path) -> None:
    context = RunContext.create("read", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Read.",
            "action": {
                "name": "read_file",
                "args": {"path": "../outside.txt", "start_line": None, "max_lines": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.SANDBOX_VIOLATION
