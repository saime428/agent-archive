from __future__ import annotations

import json
import os
import time

import pytest

from agent.core.run_store import RunStore, RunStoreError


def _write_run(root, run_id: str, *, summary: str = "summary", records: list[dict | str] | None = None):
    run_dir = root / ".agent" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    lines = []
    for record in records or []:
        if isinstance(record, str):
            lines.append(record)
        else:
            lines.append(json.dumps(record, ensure_ascii=True))
    (run_dir / "tool_calls.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return run_dir


def test_list_runs_returns_empty_when_runs_directory_missing(tmp_path) -> None:
    store = RunStore(tmp_path)

    assert store.list_runs() == []


def test_list_runs_orders_by_updated_time_descending(tmp_path) -> None:
    older = _write_run(tmp_path, "run_older", summary="older")
    time.sleep(0.01)
    newer = _write_run(tmp_path, "run_newer", summary="newer")
    os.utime(older, (older.stat().st_atime, older.stat().st_mtime))
    os.utime(newer, None)

    runs = RunStore(tmp_path).list_runs()

    assert [run.run_id for run in runs] == ["run_newer", "run_older"]
    assert runs[0].summary_path.name == "summary.md"
    assert runs[0].tool_calls_path.name == "tool_calls.jsonl"


def test_list_runs_respects_limit(tmp_path) -> None:
    _write_run(tmp_path, "run_1")
    _write_run(tmp_path, "run_2")

    runs = RunStore(tmp_path).list_runs(limit=1)

    assert len(runs) == 1


def test_show_run_reads_summary_and_tool_calls(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run_test",
        summary="# Run run_test\n\n- final: ok\n",
        records=[
            {
                "action": {"action": {"name": "write_file"}},
                "observation": {
                    "status": "ok",
                    "data": {
                        "path": "notes.txt",
                        "snapshot_path": ".agent/runs/run_test/snapshots/act_000001/original",
                        "restore_hint": "Restore by copying original back.",
                    },
                },
            }
        ],
    )

    detail = RunStore(tmp_path).show_run("run_test")

    assert detail.run_id == "run_test"
    assert "final: ok" in detail.summary
    assert len(detail.tool_calls) == 1
    assert detail.tool_calls[0].valid is True
    assert detail.snapshots == [
        {
            "path": "notes.txt",
            "snapshot_path": ".agent/runs/run_test/snapshots/act_000001/original",
            "restore_hint": "Restore by copying original back.",
        }
    ]


def test_show_run_accepts_redaction_metadata_and_redacted_content(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run_redacted",
        summary="# Run run_redacted\n\n- final: Token is [REDACTED].\n- redaction_applied: true\n",
        records=[
            {
                "action": {"action": {"name": "write_file"}},
                "observation": {
                    "status": "ok",
                    "data": {
                        "path": "notes.txt",
                        "snapshot_path": ".agent/runs/run_redacted/snapshots/act_000001/original",
                        "restore_hint": "Restore by copying original back.",
                        "content": "[REDACTED]",
                    },
                },
                "redaction": {"applied": True, "replacements": 1},
            }
        ],
    )

    detail = RunStore(tmp_path).show_run("run_redacted")

    assert "Token is [REDACTED]." in detail.summary
    assert "redaction_applied: true" in detail.summary
    assert detail.tool_calls[0].valid is True
    assert detail.tool_calls[0].data["redaction"] == {"applied": True, "replacements": 1}
    assert detail.snapshots == [
        {
            "path": "notes.txt",
            "snapshot_path": ".agent/runs/run_redacted/snapshots/act_000001/original",
            "restore_hint": "Restore by copying original back.",
        }
    ]


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "nested\\run", "..", ""])
def test_show_run_rejects_invalid_run_ids(tmp_path, run_id: str) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(RunStoreError):
        store.show_run(run_id)


def test_show_run_rejects_absolute_run_id(tmp_path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(RunStoreError):
        store.show_run(str(tmp_path / "run_test"))


def test_show_run_missing_run_raises_error(tmp_path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(RunStoreError):
        store.show_run("run_missing")


def test_show_run_missing_summary_raises_error(tmp_path) -> None:
    run_dir = tmp_path / ".agent" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(RunStoreError):
        RunStore(tmp_path).show_run("run_test")


def test_show_run_marks_invalid_jsonl_lines_without_failing(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run_test",
        records=[
            "{not-json",
            {
                "action": {"action": {"name": "done"}},
                "observation": {"status": "ok", "data": {"final": "ok"}},
            },
        ],
    )

    detail = RunStore(tmp_path).show_run("run_test")

    assert [call.valid for call in detail.tool_calls] == [False, True]
    assert "not valid JSON" in detail.tool_calls[0].error
