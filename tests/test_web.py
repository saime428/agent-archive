from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from agent.llm.fake import FakeLLMClient
from agent.web import server
from agent.web import chat_runtime
from agent.web import settings
from agent.web.chat_runtime import ChatRuntime


_NO_BODY = object()
_ROOT = object()
_BODY = object()


@contextmanager
def _running_workbench(workspace: Path) -> Iterator[tuple[str, int]]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.create_workbench_handler(workspace))
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    try:
        host, port = httpd.server_address
        yield str(host), int(port)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2.0)


def _http_request(
    workspace: Path,
    method: str,
    path: str,
    body: object = _NO_BODY,
) -> tuple[int, dict[str, str], bytes]:
    payload = None if body is _NO_BODY else body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    headers = {} if body is _NO_BODY else {"Content-Type": "application/json"}
    with _running_workbench(workspace) as (host, port):
        connection = HTTPConnection(host, port, timeout=2.0)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            return response.status, response_headers, response.read()
        finally:
            connection.close()


def _done_response(final: str = "ok") -> dict[str, object]:
    return {
        "message": "Done.",
        "action": {"name": "done", "args": {"final": final, "changed_files": [], "next_steps": []}},
    }


def _wait_for_runtime_done(runtime: ChatRuntime, job_id: str) -> dict[str, object]:
    for _ in range(400):
        payload = runtime.poll(job_id, timeout=0)
        if payload["done"]:
            return payload
        time.sleep(0.005)
    raise AssertionError("chat job did not finish")


def _wait_for_runtime_event(runtime: ChatRuntime, job_id: str, name: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    after = 0
    for _ in range(400):
        payload = runtime.poll(job_id, after=after, timeout=0)
        batch = payload["events"]
        events.extend(batch)
        after = payload["next"]
        if any(event["event"] == name for event in events):
            return events
        if payload["done"]:
            break
        time.sleep(0.005)
    raise AssertionError(f"chat job did not emit {name}")


@pytest.mark.parametrize(
    ("method", "path", "target", "body", "expected_args", "expected_kwargs"),
    [
        pytest.param("GET", "/api/health", "build_health_payload", _NO_BODY, (_ROOT,), {}, id="health"),
        pytest.param("GET", "/api/config", "build_config_payload", _NO_BODY, (_ROOT,), {}, id="config-get"),
        pytest.param("GET", "/api/chats", "_build_chats_payload", _NO_BODY, (_ROOT,), {}, id="chats"),
        pytest.param("GET", "/api/tools", "build_tools_payload", _NO_BODY, (), {}, id="tools"),
        pytest.param("GET", "/api/runs", "_build_runs_payload", _NO_BODY, (_ROOT,), {}, id="runs"),
        pytest.param("GET", "/api/files?path=src", "build_files_payload", _NO_BODY, (_ROOT, "src"), {}, id="files"),
        pytest.param(
            "GET", "/api/file?path=README.md", "build_file_payload", _NO_BODY, (_ROOT, "README.md"), {}, id="file"
        ),
        pytest.param(
            "GET",
            "/api/diff?path=a&snapshot=b",
            "build_diff_payload",
            _NO_BODY,
            (_ROOT, "a", "b"),
            {},
            id="diff",
        ),
        pytest.param(
            "GET", "/api/chats/chat_1", "_build_chat_payload", _NO_BODY, (_ROOT, "chat_1"), {}, id="chat-detail"
        ),
        pytest.param(
            "GET", "/api/runs/run_1", "_build_run_detail_payload", _NO_BODY, (_ROOT, "run_1"), {}, id="run-detail"
        ),
        pytest.param("POST", "/api/chat/turn", "_build_chat_turn_payload", {"value": "turn"}, (_ROOT, _BODY), {}, id="turn"),
        pytest.param(
            "POST",
            "/api/chat/start",
            "runtime.start",
            {"message": "  hi  ", "session_id": ""},
            (),
            {"message": "hi", "session_id": ""},
            id="start",
        ),
        pytest.param(
            "POST",
            "/api/chat/approval",
            "runtime.decide",
            {"job_id": "job_1", "approve": True},
            (),
            {"job_id": "job_1", "approve": True},
            id="approval",
        ),
        pytest.param(
            "POST", "/api/chat/rename", "_build_chat_rename_payload", {"value": "rename"}, (_ROOT, _BODY), {}, id="rename"
        ),
        pytest.param(
            "POST", "/api/chat/delete", "_build_chat_delete_payload", {"value": "delete"}, (_ROOT, _BODY), {}, id="delete"
        ),
        pytest.param("POST", "/api/config", "build_save_config_payload", {"value": "config"}, (_ROOT, _BODY), {}, id="config-post"),
        pytest.param(
            "POST",
            "/api/snapshot/restore",
            "build_restore_snapshot_payload",
            {"value": "restore"},
            (_ROOT, _BODY),
            {},
            id="restore",
        ),
        pytest.param(
            "POST", "/api/file/save", "build_save_file_payload", {"value": "save"}, (_ROOT, _BODY), {}, id="save"
        ),
    ],
)
def test_workbench_routes_dispatch_to_expected_builder(
    monkeypatch,
    tmp_path,
    method: str,
    path: str,
    target: str,
    body: object,
    expected_args: tuple[object, ...],
    expected_kwargs: dict[str, object],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def sentinel(*args: object, **kwargs: object) -> dict[str, str]:
        calls.append((args, kwargs))
        return {"target": target}

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def start(self, *, message: str, session_id: str | None) -> dict[str, str]:
            return sentinel(message=message, session_id=session_id)

        def decide(self, *, job_id: str, approve: bool) -> dict[str, str]:
            return sentinel(job_id=job_id, approve=approve)

    monkeypatch.setattr(server, "ChatRuntime", FakeRuntime)
    if not target.startswith("runtime."):
        monkeypatch.setattr(server, target, sentinel)

    status, _headers, response = _http_request(workspace, method, path, body)

    resolved_args = tuple(
        workspace.resolve() if item is _ROOT else body if item is _BODY else item for item in expected_args
    )
    assert status == 200
    assert json.loads(response) == {"target": target}
    assert calls == [(resolved_args, expected_kwargs)]


def test_workbench_sse_route_reuses_preflight_and_closes_after_done_batch(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[str, int, float]] = []
    event = {"event": "final", "sequence": 0, "final": "ok"}

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def poll(self, job_id: str, *, after: int, timeout: float) -> dict[str, object]:
            calls.append((job_id, after, timeout))
            return {"job_id": job_id, "events": [event], "done": True, "next": 1}

    monkeypatch.setattr(server, "ChatRuntime", FakeRuntime)

    status, headers, response = _http_request(workspace, "GET", "/api/chat/events?job_id=job_1")

    assert status == 200
    assert headers["content-type"] == "text/event-stream; charset=utf-8"
    assert headers["connection"] == "close"
    assert b"event: final" in response
    assert json.dumps(event, ensure_ascii=False).encode("utf-8") in response
    assert calls == [("job_1", 0, 0)]


def test_workbench_sse_route_closes_when_later_poll_loses_job(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[str, int, float]] = []

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def poll(self, job_id: str, *, after: int, timeout: float) -> dict[str, object]:
            calls.append((job_id, after, timeout))
            if len(calls) == 1:
                return {"job_id": job_id, "events": [], "done": False, "next": 0}
            raise ValueError(f"Unknown chat job: {job_id}")

    monkeypatch.setattr(server, "ChatRuntime", FakeRuntime)

    status, headers, response = _http_request(workspace, "GET", "/api/chat/events?job_id=job_pruned")

    assert status == 200
    assert headers["connection"] == "close"
    assert response == b""
    assert calls == [("job_pruned", 0, 0), ("job_pruned", 0, 10.0)]


def test_workbench_sse_route_rejects_unknown_job_before_headers(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, headers, response = _http_request(workspace, "GET", "/api/chat/events?job_id=job_missing")

    assert status == 400
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert json.loads(response) == {"error": "Unknown chat job: job_missing"}


def test_workbench_static_fallback_and_unknown_post(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, headers, _response = _http_request(workspace, "GET", "/")
    unknown_status, _unknown_headers, unknown_response = _http_request(workspace, "POST", "/api/unknown")

    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert unknown_status == 404
    assert json.loads(unknown_response) == {"error": "Unknown endpoint: /api/unknown"}


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        pytest.param("/api/config", _NO_BODY, "JSON body is required.", id="missing-body"),
        pytest.param("/api/chat/start", {"message": " "}, "message is required.", id="empty-message"),
        pytest.param(
            "/api/chat/approval",
            {"job_id": "job_1", "approve": "yes"},
            "approve must be a boolean.",
            id="approval-type",
        ),
    ],
)
def test_workbench_post_validation_errors(tmp_path, path: str, body: object, message: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(workspace, "POST", path, body)

    assert status == 400
    assert json.loads(response) == {"error": message}


def test_workbench_rejects_invalid_json(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(workspace, "POST", "/api/config", b"{")

    assert status == 400
    assert json.loads(response)["error"].startswith("Invalid JSON body: ")


@pytest.mark.parametrize(
    ("method", "path", "target", "kind", "expected_status"),
    [
        pytest.param("GET", "/api/health", "build_health_payload", "config", 400, id="get-config"),
        pytest.param("GET", "/api/health", "build_health_payload", "value", 400, id="get-value"),
        pytest.param("GET", "/api/health", "build_health_payload", "sandbox", 400, id="get-sandbox"),
        pytest.param("GET", "/api/runs", "_build_runs_payload", "run-store", 404, id="get-run-store"),
        pytest.param("GET", "/api/health", "build_health_payload", "os", 500, id="get-os"),
        pytest.param("POST", "/api/config", "build_save_config_payload", "config", 400, id="post-config"),
        pytest.param("POST", "/api/config", "build_save_config_payload", "value", 400, id="post-value"),
        pytest.param("POST", "/api/config", "build_save_config_payload", "provider", 502, id="post-provider"),
        pytest.param("POST", "/api/config", "build_save_config_payload", "os", 500, id="post-os"),
    ],
)
def test_workbench_maps_handler_errors(
    monkeypatch,
    tmp_path,
    method: str,
    path: str,
    target: str,
    kind: str,
    expected_status: int,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    errors = {
        "config": server.ConfigError("sentinel"),
        "value": ValueError("sentinel"),
        "sandbox": server.SandboxError("SANDBOX_VIOLATION", "sentinel"),
        "run-store": server.RunStoreError("sentinel"),
        "provider": server.DeepSeekError("sentinel"),
        "os": OSError("sentinel"),
    }

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise errors[kind]

    monkeypatch.setattr(server, target, fail)

    status, _headers, response = _http_request(workspace, method, path, {} if method == "POST" else _NO_BODY)

    assert status == expected_status
    assert json.loads(response) == {"error": "sentinel"}


def test_chat_start_rejects_unsafe_session_id_before_llm(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm_called = threading.Event()

    def fail_llm(_config):
        llm_called.set()
        raise AssertionError("LLM must not be created for an unsafe session id")

    monkeypatch.setattr(
        server,
        "ChatRuntime",
        lambda root: ChatRuntime(root, llm_factory=fail_llm),
    )

    status, _headers, response = _http_request(
        workspace,
        "POST",
        "/api/chat/start",
        {"message": "x", "session_id": "../runs"},
    )
    if status != 400:
        llm_called.wait(1.0)

    assert status == 400
    assert "chat session id" in json.loads(response)["error"]
    assert not llm_called.is_set()


@pytest.mark.parametrize("entry", ["start", "poll", "decide"])
def test_chat_runtime_prunes_completed_jobs_at_every_entry(tmp_path, entry: str) -> None:
    now = [100.0]
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient(), clock=lambda: now[0], job_ttl=10.0)
    started = runtime.start(message="old", session_id=None)
    _wait_for_runtime_done(runtime, started["job_id"])
    now[0] += 11.0

    if entry == "start":
        runtime.start(message="new", session_id=None)

    with pytest.raises(ValueError, match=f"Unknown chat job: {started['job_id']}"):
        if entry == "decide":
            runtime.decide(job_id=started["job_id"], approve=True)
        else:
            runtime.poll(started["job_id"], timeout=0)


def test_chat_runtime_does_not_prune_active_job_and_negative_timeout_is_nonblocking(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()
    now = [100.0]

    class BlockingLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: BlockingLLM(), clock=lambda: now[0], job_ttl=1.0)
    started = runtime.start(message="wait", session_id=None)
    assert entered.wait(1.0)
    now[0] += 100.0

    began = time.monotonic()
    payload = runtime.poll(started["job_id"], timeout=-1.0)
    elapsed = time.monotonic() - began

    assert payload["done"] is False
    assert elapsed < 0.1
    release.set()
    _wait_for_runtime_done(runtime, started["job_id"])


def test_chat_runtime_registry_is_instance_local(tmp_path) -> None:
    first = ChatRuntime(tmp_path / "first", llm_factory=lambda _config: FakeLLMClient())
    second = ChatRuntime(tmp_path / "second", llm_factory=lambda _config: FakeLLMClient())
    started = first.start(message="hi", session_id=None)

    with pytest.raises(ValueError, match=f"Unknown chat job: {started['job_id']}"):
        second.poll(started["job_id"], timeout=0)


def test_chat_runtime_poll_uses_event_offsets_and_sequence_numbers(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    started = runtime.start(message="hi", session_id=None)
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    events = complete["events"]

    assert [event["sequence"] for event in events] == list(range(len(events)))
    tail = runtime.poll(started["job_id"], after=1, timeout=0)
    assert tail["events"] == events[1:]
    assert tail["next"] == len(events)
    with pytest.raises(ValueError, match=r"after must be non-negative\."):
        runtime.poll(started["job_id"], after=-1, timeout=0)


def test_config_update_accepts_openai_compat_provider(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = settings.build_save_config_payload(
        workspace,
        {
            "provider": "openai-compat",
            "model": "gpt-4o-mini",
            "sandbox": "workspace-write",
            "approval": "risky-confirm",
            "dry_run": True,
            "web_search_enabled": True,
            "computer_read_enabled": True,
            "default_skills": ["code-dev"],
        },
    )

    assert payload["status"] == "ok"
    assert payload["config"]["provider"] == "openai-compat"


def test_build_health_payload_reports_native_tools_disabled_by_default(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = settings.build_health_payload(workspace)

    assert payload["native_tools"] is False


def test_config_update_accepts_native_tools_boolean(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = settings.build_save_config_payload(workspace, {"native_tools": True})

    assert payload["status"] == "ok"
    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    assert "native_tools = true" in config_text


def test_config_update_rejects_non_boolean_native_tools(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError):
        settings.build_save_config_payload(workspace, {"native_tools": "yes"})


def test_chat_runtime_streams_tagged_model_chunks(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")

    class StreamingFake:
        def chat_tools(self, messages, tools, *, temperature=None):
            raise AssertionError("streaming path expected when stream_handler is provided")

        def stream_chat_tools(self, messages, tools, *, temperature=None):
            yield ("thinking", "planning")
            yield ("args", '{"final"')
            return {
                "message": "",
                "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
            }

    runtime = ChatRuntime(workspace, llm_factory=lambda _config: StreamingFake())
    started = runtime.start(message="hi", session_id=None)
    events = _wait_for_runtime_done(runtime, started["job_id"])["events"]

    chunk_events = [event for event in events if event.get("event") == "model_stream_chunk"]
    assert [(event["kind"], event["text"]) for event in chunk_events] == [
        ("thinking", "planning"),
        ("args", '{"final"'),
    ]
    assert any(event.get("event") == "final" for event in events)


def test_chat_runtime_batches_tiny_model_chunks(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")
    streamed = "x" * 130

    class StreamingFake:
        def chat_tools(self, messages, tools, *, temperature=None):
            raise AssertionError("streaming path expected when stream_handler is provided")

        def stream_chat_tools(self, messages, tools, *, temperature=None):
            for character in streamed:
                yield ("thinking", character)
            return {
                "message": "",
                "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
            }

    runtime = ChatRuntime(workspace, llm_factory=lambda _config: StreamingFake())
    started = runtime.start(message="hi", session_id=None)
    events = _wait_for_runtime_done(runtime, started["job_id"])["events"]

    chunk_events = [event for event in events if event.get("event") == "model_stream_chunk"]
    assert "".join(event["text"] for event in chunk_events) == streamed
    assert [event["chunk_chars"] for event in chunk_events] == [len(event["text"]) for event in chunk_events]
    assert len(chunk_events) <= 3


def _write_llm() -> FakeLLMClient:
    return FakeLLMClient(
        actions=[
            {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "notes.txt", "content": "hello\n", "create_parents": False},
                },
            },
            {
                "message": "Done.",
                "action": {
                    "name": "done",
                    "args": {"final": "Wrote notes.", "changed_files": ["notes.txt"], "next_steps": []},
                },
            },
        ]
    )


@pytest.mark.parametrize(
    ("approve", "decision_event", "file_exists"),
    [(True, "approval_granted", True), (False, "approval_denied", False)],
)
def test_chat_runtime_applies_approval_decision(tmp_path, approve: bool, decision_event: str, file_exists: bool) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = ChatRuntime(workspace, llm_factory=lambda _config: _write_llm())
    started = runtime.start(message="write notes", session_id=None)
    approval_events = _wait_for_runtime_event(runtime, started["job_id"], "approval_required")
    approval = approval_events[-1]

    assert approval["action"] == "write_file"
    assert approval["reason"] == "Action requires approval before execution."
    assert runtime.decide(job_id=started["job_id"], approve=approve) == {
        "status": "ok",
        "job_id": started["job_id"],
        "approved": approve,
    }
    with pytest.raises(ValueError):
        runtime.decide(job_id=started["job_id"], approve=approve)

    complete = _wait_for_runtime_done(runtime, started["job_id"])
    names = [event["event"] for event in complete["events"]]
    assert decision_event in names
    assert "final" in names
    assert (workspace / "notes.txt").exists() is file_exists


def test_chat_runtime_rejects_decision_before_pending_and_after_finish(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class GateLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: GateLLM())
    started = runtime.start(message="wait", session_id=None)
    assert entered.wait(1.0)
    with pytest.raises(ValueError, match=r"chat job has no pending approval\."):
        runtime.decide(job_id=started["job_id"], approve=True)

    release.set()
    _wait_for_runtime_done(runtime, started["job_id"])
    with pytest.raises(ValueError, match=r"chat job is already finished\."):
        runtime.decide(job_id=started["job_id"], approve=True)


def test_chat_runtime_marks_expired_decision_and_wakes_worker(tmp_path) -> None:
    now = [100.0]
    runtime = ChatRuntime(
        tmp_path,
        llm_factory=lambda _config: _write_llm(),
        clock=lambda: now[0],
        approval_timeout=1.0,
    )
    started = runtime.start(message="write notes", session_id=None)
    _wait_for_runtime_event(runtime, started["job_id"], "approval_required")
    now[0] += 2.0

    with pytest.raises(ValueError, match=r"chat approval has expired\."):
        runtime.decide(job_id=started["job_id"], approve=True)

    complete = _wait_for_runtime_done(runtime, started["job_id"])
    names = [event["event"] for event in complete["events"]]
    assert names.index("approval_required") < names.index("approval_timed_out") < names.index("final")
    assert not (tmp_path / "notes.txt").exists()


def test_chat_runtime_times_out_and_rejects_late_decision(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: _write_llm(), approval_timeout=0.01)
    started = runtime.start(message="write notes", session_id=None)
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    names = [event["event"] for event in complete["events"]]

    assert names.index("approval_required") < names.index("approval_timed_out") < names.index("final")
    with pytest.raises(ValueError):
        runtime.decide(job_id=started["job_id"], approve=True)
    assert not (tmp_path / "notes.txt").exists()


@pytest.mark.parametrize("failure", ["factory", "turn"])
def test_chat_runtime_reports_worker_errors_and_completes(tmp_path, failure: str) -> None:
    class FailingLLM:
        def chat(self, _messages, *, temperature=None):
            raise RuntimeError("turn exploded")

    def factory(_config):
        if failure == "factory":
            raise RuntimeError("factory exploded")
        return FailingLLM()

    runtime = ChatRuntime(tmp_path, llm_factory=factory)
    started = runtime.start(message="fail", session_id=None)
    _wait_for_runtime_event(runtime, started["job_id"], "error")
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    errors = [event["error"] for event in complete["events"] if event["event"] == "error"]

    assert errors == [f"{failure} exploded"]
    assert complete["done"] is True


def test_chat_runtime_start_failures_do_not_call_llm_factory(tmp_path) -> None:
    called = threading.Event()

    def factory(_config):
        called.set()
        return FakeLLMClient()

    invalid_config = tmp_path / "invalid-config"
    (invalid_config / ".agent").mkdir(parents=True)
    (invalid_config / ".agent" / "config.toml").write_text('provider = "invalid"\n', encoding="utf-8")
    mismatch = tmp_path / "mismatch"
    session_dir = mismatch / ".agent" / "chats" / "chat_expected"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        json.dumps({"session_id": "chat_other", "created_at": "x", "updated_at": "x", "turns": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ChatRuntime(invalid_config, llm_factory=factory).start(message="hi", session_id=None)
    with pytest.raises(ValueError, match="does not match"):
        ChatRuntime(mismatch, llm_factory=factory).start(message="hi", session_id="chat_expected")
    assert not called.is_set()


def test_chat_runtime_start_rejects_redirected_chat_storage_before_llm(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "redirected"
    (workspace / ".agent").mkdir(parents=True)
    target.mkdir()
    chats = workspace / ".agent" / "chats"
    try:
        chats.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        if os.name != "nt":
            pytest.skip(f"symlink creation is unavailable: {exc}")
        junction = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(chats), str(target)],
            capture_output=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(f"junction creation is unavailable: {exc}")
    called = threading.Event()

    def factory(_config):
        called.set()
        return FakeLLMClient()

    with pytest.raises(ValueError, match="redirect"):
        ChatRuntime(workspace, llm_factory=factory).start(message="hi", session_id=None)
    assert not called.is_set()


def test_chat_runtime_rolls_back_job_when_thread_start_fails(monkeypatch, tmp_path) -> None:
    class FailingThread:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(chat_runtime.uuid, "uuid4", lambda: SimpleNamespace(hex="deadbeefcafe0000"))
    monkeypatch.setattr(chat_runtime.threading, "Thread", FailingThread)
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())

    with pytest.raises(RuntimeError, match="thread start failed"):
        runtime.start(message="hi", session_id=None)
    with pytest.raises(ValueError, match="Unknown chat job: job_deadbeefcafe"):
        runtime.poll("job_deadbeefcafe", timeout=0)


def test_chat_runtime_public_surface_is_start_poll_decide_only() -> None:
    public = {name for name in vars(ChatRuntime) if not name.startswith("_")}
    assert public == {"start", "poll", "decide"}
