from agent.core.actions import ErrorCode, make_error_observation, parse_model_action
from agent.core.budget import ContextBudget
from agent.core.context import RunContext
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.filesystem import execute_tool


def _parse_action(context: RunContext, name: str, args: dict, *, action_index: int = 1):
    return parse_model_action(
        {
            "message": f"Run {name}.",
            "action": {"name": name, "args": args},
        },
        run_id=context.run_id,
        action_index=action_index,
        created_at=context.created_at,
    )


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


def test_read_file_uses_context_budget_for_lines_and_chars(tmp_path) -> None:
    (tmp_path / "large.txt").write_text("abcdef\nghijkl\nmnopqr\n", encoding="utf-8")
    context = RunContext.create(
        "read",
        cwd=tmp_path,
        run_id="run_tools",
        budget=ContextBudget(file_read_max_lines=2, file_read_max_chars=8),
    )
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
    assert observation.data["content"] == "abcdef\ng\n[truncated]"
    assert observation.data["truncated"] is True


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


def test_search_files_uses_context_budget_for_matches_and_excerpt(tmp_path) -> None:
    for index in range(3):
        (tmp_path / f"file_{index}.txt").write_text("needle abcdef\n", encoding="utf-8")
    context = RunContext.create(
        "search",
        cwd=tmp_path,
        run_id="run_tools",
        budget=ContextBudget(search_max_matches=1, search_excerpt_chars=8),
    )
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
    assert observation.data["total_matches"] == 3
    assert observation.data["truncated"] is True
    assert len(observation.data["matches"]) == 1
    assert observation.data["matches"][0]["excerpt"] == "needle a"


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


def test_apply_patch_replaces_single_first_match_and_snapshots(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello world\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {"edits": [{"path": "notes.txt", "old": "hello", "new": "hi"}]},
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert target.read_text(encoding="utf-8") == "hi world\n"
    assert observation.data is not None
    assert observation.data["changed_files"] == [str(target.resolve())]
    assert observation.data["replacements"] == [{"path": str(target.resolve()), "count": 1}]
    assert len(observation.data["snapshots"]) == 1
    snapshot = observation.data["snapshots"][0]
    assert snapshot["path"] == str(target.resolve())
    assert snapshot["previously_existed"] is True
    assert (tmp_path / snapshot["snapshot_path"]).read_text(encoding="utf-8") == "hello world\n"
    assert observation.data["restore_hints"][0]["path"] == str(target.resolve())


def test_apply_patch_replaces_all_matches(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("one fish, one dish\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {
            "edits": [
                {
                    "path": "notes.txt",
                    "old": "one",
                    "new": "two",
                    "occurrence": "all",
                }
            ]
        },
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert target.read_text(encoding="utf-8") == "two fish, two dish\n"
    assert observation.data is not None
    assert observation.data["replacements"] == [{"path": str(target.resolve()), "count": 2}]


def test_apply_patch_changes_multiple_files_with_distinct_snapshots(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {
            "edits": [
                {"path": "first.txt", "old": "alpha", "new": "ALPHA"},
                {"path": "second.txt", "old": "beta", "new": "BETA"},
            ]
        },
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "ok"
    assert first.read_text(encoding="utf-8") == "ALPHA\n"
    assert second.read_text(encoding="utf-8") == "BETA\n"
    assert observation.data is not None
    assert observation.data["changed_files"] == [str(first.resolve()), str(second.resolve())]
    snapshot_paths = [item["snapshot_path"] for item in observation.data["snapshots"]]
    assert len(snapshot_paths) == 2
    assert snapshot_paths[0] != snapshot_paths[1]
    assert (tmp_path / snapshot_paths[0]).read_text(encoding="utf-8") == "alpha\n"
    assert (tmp_path / snapshot_paths[1]).read_text(encoding="utf-8") == "beta\n"


def test_apply_patch_missing_old_returns_tool_failed_without_snapshot(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello world\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {"edits": [{"path": "notes.txt", "old": "missing", "new": "hi"}]},
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED
    assert target.read_text(encoding="utf-8") == "hello world\n"
    assert not (tmp_path / ".agent" / "runs" / "run_patch" / "snapshots").exists()


def test_apply_patch_first_rejects_ambiguous_match_without_change(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("same same\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {"edits": [{"path": "notes.txt", "old": "same", "new": "once"}]},
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED
    assert target.read_text(encoding="utf-8") == "same same\n"


def test_apply_patch_rejects_binary_file_without_change(tmp_path) -> None:
    target = tmp_path / "image.bin"
    target.write_bytes(b"\x00old\x00")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {"edits": [{"path": "image.bin", "old": "old", "new": "new"}]},
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED
    assert target.read_bytes() == b"\x00old\x00"


def test_apply_patch_rejects_protected_and_escape_paths(tmp_path) -> None:
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    protected_cases = [
        ".agent/runs/run_patch/summary.md",
        ".git/config",
        "__pycache__/cache.pyc",
        "../outside.txt",
    ]
    for index, path in enumerate(protected_cases, start=1):
        action = _parse_action(
            context,
            "apply_patch",
            {"edits": [{"path": path, "old": "old", "new": "new"}]},
            action_index=index,
        )

        observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=index)

        assert observation.status == "error"
        assert observation.error is not None
        assert observation.error.code == ErrorCode.SANDBOX_VIOLATION


def test_apply_patch_does_not_partially_write_when_later_edit_fails(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    context = RunContext.create("patch", cwd=tmp_path, run_id="run_patch")
    action = _parse_action(
        context,
        "apply_patch",
        {
            "edits": [
                {"path": "first.txt", "old": "alpha", "new": "ALPHA"},
                {"path": "second.txt", "old": "missing", "new": "BETA"},
            ]
        },
    )

    observation = execute_tool(action, context, WorkspaceSandbox(tmp_path), observation_index=1)

    assert observation.status == "error"
    assert observation.error is not None
    assert observation.error.code == ErrorCode.TOOL_FAILED
    assert first.read_text(encoding="utf-8") == "alpha\n"
    assert second.read_text(encoding="utf-8") == "beta\n"
    assert not (tmp_path / ".agent" / "runs" / "run_patch" / "snapshots").exists()
