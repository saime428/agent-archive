from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from agent.core.automation import AutomationError, AutomationStore, AutomationWorker
from agent.core.run_lease import WorkspaceRunLease
from agent.llm.base import ProviderCapabilities
from agent.llm.fake import FakeLLMClient


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


class RecordingRuntime:
    def __init__(self, workspace) -> None:
        self.workspace = workspace
        self.closed = False

    def discover_tools(self) -> tuple:
        return ()

    def close(self) -> None:
        self.closed = True


def _enabled(store: AutomationStore, *, task: str = "inspect project"):
    definition = store.add_definition(task=task, interval_seconds=60, now=NOW)
    return store.enable_definition(definition.automation_id, now=NOW)


def test_automation_definition_claims_only_latest_slot_once(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    definition = store.add_definition(
        task="inspect parser tests",
        interval_seconds=60,
        skills=("code-dev",),
        timeout_seconds=30,
        now=NOW,
    )

    assert definition.status == "disabled"
    assert store.claim_due(now=NOW) == []

    enabled = store.enable_definition(definition.automation_id, now=NOW)
    first = store.claim_due(now=NOW)

    assert enabled.status == "enabled"
    assert len(first) == 1
    assert first[0].scheduled_for == NOW.isoformat()
    assert store.claim_due(now=NOW) == []
    store.finish_attempt(first[0].attempt_id, status="succeeded", now=NOW)

    latest = store.claim_due(now=NOW + timedelta(minutes=3, seconds=5))

    assert len(latest) == 1
    assert latest[0].scheduled_for == (NOW + timedelta(minutes=3)).isoformat()
    assert len(store.list_attempts()) == 2

    disabled = store.disable_definition(definition.automation_id, now=NOW + timedelta(minutes=4))

    assert disabled.status == "disabled"
    assert store.claim_due(now=NOW + timedelta(minutes=10)) == []
    assert [item.status for item in store.definition_history(definition.automation_id)] == [
        "disabled",
        "enabled",
        "disabled",
    ]


def test_automation_concurrent_claim_has_one_winner(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store)
    barrier = threading.Barrier(2)

    def claim(_index: int) -> int:
        barrier.wait()
        return len(AutomationStore(tmp_path).claim_due(now=NOW))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(claim, range(2)))

    assert results == [0, 1]
    assert len(store.list_attempts()) == 1


def test_automation_cancel_and_recovery_write_one_terminal_notification(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store)
    attempt = store.claim_due(now=NOW)[0]
    running = store.mark_running(attempt.attempt_id, now=NOW)

    requested = store.request_cancel(attempt.attempt_id)

    assert running.status == "running"
    assert requested.status == "cancel_requested"
    assert store.is_cancel_requested(attempt.attempt_id) is True
    assert store.list_attempts()[0].status == "cancel_requested"

    recovered = store.recover_incomplete(now=NOW + timedelta(seconds=1))

    assert [item.status for item in recovered] == ["cancelled"]
    assert store.list_attempts()[0].status == "cancelled"
    assert store.list_notifications()[0].status == "cancelled"
    with pytest.raises(AutomationError, match="terminal"):
        store.request_cancel(attempt.attempt_id)
    with pytest.raises(AutomationError, match="terminal"):
        store.finish_attempt(attempt.attempt_id, status="failed", error="second terminal", now=NOW)

    next_attempt = store.claim_due(now=NOW + timedelta(minutes=1))[0]
    store.mark_running(next_attempt.attempt_id, now=NOW + timedelta(minutes=1))
    with pytest.raises(AutomationError, match="Succeeded"):
        store.finish_attempt(next_attempt.attempt_id, status="succeeded", error="impossible", now=NOW)
    interrupted = store.recover_incomplete(now=NOW + timedelta(minutes=1, seconds=1))

    assert [item.status for item in interrupted] == ["interrupted"]
    assert [item.status for item in store.list_notifications()] == ["cancelled", "interrupted"]


def test_automation_store_rejects_corrupt_linked_and_non_atomic_state(tmp_path, monkeypatch) -> None:
    corrupt_root = tmp_path / "corrupt" / ".agent" / "automations"
    corrupt_root.mkdir(parents=True)
    (corrupt_root / "definitions.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(AutomationError, match="parse"):
        AutomationStore(tmp_path / "corrupt").list_definitions()
    with pytest.raises(AutomationError, match="too large"):
        AutomationStore(tmp_path / "bounded").add_definition(
            task="x" * 20_001,
            interval_seconds=60,
            now=NOW,
        )

    linked_workspace = tmp_path / "linked"
    linked_root = linked_workspace / ".agent" / "automations"
    linked_root.parent.mkdir(parents=True)
    external = tmp_path / "external-automations"
    external.mkdir()
    try:
        linked_root.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available on this host.")

    with pytest.raises(AutomationError, match="real directory"):
        AutomationStore(linked_workspace).list_definitions()

    store = AutomationStore(tmp_path / "atomic")
    store.add_definition(task="first", interval_seconds=60, now=NOW)
    before = store.definitions_path.read_bytes()

    def fail_replace(_source, _target) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("agent._user_store.os.replace", fail_replace)

    with pytest.raises(AutomationError, match="write"):
        store.add_definition(task="second", interval_seconds=60, now=NOW)
    assert store.definitions_path.read_bytes() == before


def test_automation_worker_runs_once_closes_runtime_and_does_not_repeat_slot(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store)
    runtimes: list[RecordingRuntime] = []

    def runtime_factory(workspace):
        runtime = RecordingRuntime(workspace)
        runtimes.append(runtime)
        return runtime

    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: FakeLLMClient(),
        runtime_factory=runtime_factory,
        now=lambda: NOW,
    )

    completed = worker.run_once()

    assert [item.status for item in completed] == ["succeeded"]
    assert completed[0].summary_path is not None
    assert (tmp_path / completed[0].summary_path).is_file()
    assert runtimes[0].closed is True
    assert worker.run_once() == []
    assert len(store.list_attempts()) == 1


def test_automation_worker_records_busy_workspace_as_failure_notification(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store)
    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: FakeLLMClient(),
        runtime_factory=RecordingRuntime,
        now=lambda: NOW,
    )

    with WorkspaceRunLease.acquire(tmp_path, owner={"kind": "test"}):
        completed = worker.run_once()

    assert [item.status for item in completed] == ["failed"]
    assert "active agent turn" in (completed[0].error or "").lower()
    assert store.list_notifications() == completed


def test_automation_worker_fails_when_an_explicit_skill_is_missing(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    definition = store.add_definition(
        task="inspect with missing skill",
        interval_seconds=60,
        skills=("missing-skill",),
        now=NOW,
    )
    store.enable_definition(definition.automation_id, now=NOW)
    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: FakeLLMClient(),
        runtime_factory=RecordingRuntime,
        now=lambda: NOW,
    )

    completed = worker.run_once()

    assert [item.status for item in completed] == ["failed"]
    assert "Unknown skill: missing-skill" in (completed[0].error or "")
    assert store.list_notifications() == completed


def test_automation_worker_never_auto_approves_confirmation_required_action(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store, task="write notes")
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "notes.txt", "content": "blocked\n", "create_parents": False},
                },
            }
        ]
    )
    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: llm,
        runtime_factory=RecordingRuntime,
        now=lambda: NOW,
    )

    completed = worker.run_once()

    assert [item.status for item in completed] == ["failed"]
    assert not (tmp_path / "notes.txt").exists()
    tool_calls = (tmp_path / ".agent" / "runs" / completed[0].run_id / "tool_calls.jsonl").read_text(
        encoding="utf-8"
    )
    assert "APPROVAL_REQUIRED" in tool_calls
    assert store.list_notifications() == completed


def test_automation_worker_observes_durable_cancel_during_stream(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _enabled(store, task="stream slowly")
    stream_started = threading.Event()

    class SlowStreamingLLM:
        capabilities = ProviderCapabilities(streaming=True, native_tools=False)

        def chat(self, _messages):
            raise AssertionError("Automation should use the streaming seam when available.")

        def stream_chat(self, _messages):
            payload = json.dumps(
                {
                    "message": "Done.",
                    "action": {
                        "name": "done",
                        "args": {"final": "too late", "changed_files": [], "next_steps": []},
                    },
                }
            )
            stream_started.set()
            for character in payload:
                time.sleep(0.005)
                yield character

    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: SlowStreamingLLM(),
        runtime_factory=RecordingRuntime,
        now=lambda: NOW,
    )
    result: list = []
    thread = threading.Thread(target=lambda: result.extend(worker.run_once()), daemon=True)
    thread.start()
    assert stream_started.wait(timeout=2)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        attempts = store.list_attempts()
        if attempts and attempts[0].status == "running":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Automation attempt did not enter running state.")

    store.request_cancel(attempts[0].attempt_id)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert [item.status for item in result] == ["cancelled"]
    assert store.list_notifications()[0].status == "cancelled"


def test_automation_worker_maps_whole_run_deadline_to_timed_out_notification(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    definition = store.add_definition(
        task="stream beyond deadline",
        interval_seconds=60,
        timeout_seconds=1,
        now=NOW,
    )
    store.enable_definition(definition.automation_id, now=NOW)

    class DeadlineStreamingLLM:
        capabilities = ProviderCapabilities(streaming=True, native_tools=False)

        def chat(self, _messages):
            raise AssertionError("Automation should use the streaming seam when available.")

        def stream_chat(self, _messages):
            while True:
                time.sleep(0.02)
                yield "x"

    worker = AutomationWorker(
        tmp_path,
        llm_factory=lambda _config: DeadlineStreamingLLM(),
        runtime_factory=RecordingRuntime,
        now=lambda: NOW,
    )

    completed = worker.run_once()

    assert [item.status for item in completed] == ["timed_out"]
    assert store.list_notifications() == completed
