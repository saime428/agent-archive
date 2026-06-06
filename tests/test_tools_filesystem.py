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


def test_search_files_glob_matches_python_paths(tmp_path) -> None:
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "*.py", "path": ".", "max_matches": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["matches"] == [
        {"path": "main.py", "kind": "path", "line": None, "excerpt": None}
    ]


def test_search_files_text_matches_line_and_excerpt(tmp_path) -> None:
    (tmp_path / "app.py").write_text("def hello():\n    return 'needle'\n", encoding="utf-8")
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "needle", "path": None, "max_matches": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["matches"] == [
        {"path": "app.py", "kind": "text", "line": 2, "excerpt": "    return 'needle'"}
    ]


def test_search_files_truncates_at_max_matches(tmp_path) -> None:
    for index in range(3):
        (tmp_path / f"file_{index}.txt").write_text("needle\n", encoding="utf-8")
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "needle", "path": ".", "max_matches": 2},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["total_matches"] == 3
    assert observation.data["truncated"] is True
    assert len(observation.data["matches"]) == 2


def test_search_files_does_not_text_scan_binary_file(tmp_path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\x00needle\x00")
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "needle", "path": ".", "max_matches": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert observation.data["matches"] == []


def test_search_files_skips_internal_run_state(tmp_path) -> None:
    internal_file = tmp_path / ".agent" / "runs" / "run_1" / "summary.md"
    internal_file.parent.mkdir(parents=True)
    internal_file.write_text("needle\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("needle\n", encoding="utf-8")
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "needle", "path": ".", "max_matches": None},
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert observation.data is not None
    assert [match["path"] for match in observation.data["matches"]] == ["visible.txt"]


def test_search_files_returns_sandbox_error_for_path_escape(tmp_path) -> None:
    context = RunContext.create("search", cwd=tmp_path, run_id="run_tools")
    action = parse_model_action(
        {
            "message": "Search.",
            "action": {
                "name": "search_files",
                "args": {"query": "needle", "path": "../", "max_matches": None},
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


def test_write_file_creates_new_file_with_missing_snapshot(tmp_path) -> None:
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
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
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello\n"
    assert observation.data is not None
    assert observation.data["path"] == str((tmp_path / "notes.txt").resolve())
    assert observation.data["bytes_written"] == len("hello\n".encode("utf-8"))
    assert observation.data["previously_existed"] is False
    assert "delet" in observation.data["restore_hint"].lower()
    snapshot_path = tmp_path / observation.data["snapshot_path"]
    assert snapshot_path.exists()
    assert "previously_existed" in snapshot_path.read_text(encoding="utf-8")


def test_write_file_overwrites_existing_file_with_snapshot_content(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": "notes.txt",
                    "content": "new\n",
                    "create_parents": False,
                },
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert observation.data is not None
    assert observation.data["previously_existed"] is True
    snapshot_path = tmp_path / observation.data["snapshot_path"]
    assert snapshot_path.read_text(encoding="utf-8") == "old\n"


def test_write_file_parent_missing_without_create_parents_returns_tool_failed(tmp_path) -> None:
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": "nested/notes.txt",
                    "content": "hello\n",
                    "create_parents": False,
                },
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


def test_write_file_create_parents_creates_directory(tmp_path) -> None:
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": "nested/notes.txt",
                    "content": "hello\n",
                    "create_parents": True,
                },
            },
        },
        run_id=context.run_id,
        action_index=1,
        created_at=context.created_at,
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert (tmp_path / "nested" / "notes.txt").read_text(encoding="utf-8") == "hello\n"


def test_write_file_rejects_escape_path(tmp_path) -> None:
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": "../outside.txt",
                    "content": "hello\n",
                    "create_parents": False,
                },
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


def test_write_file_rejects_protected_internal_state(tmp_path) -> None:
    context = RunContext.create("write", cwd=tmp_path, run_id="run_write")
    action = parse_model_action(
        {
            "message": "Write.",
            "action": {
                "name": "write_file",
                "args": {
                    "path": ".agent/runs/run_write/summary.md",
                    "content": "tamper\n",
                    "create_parents": True,
                },
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
