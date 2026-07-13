from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from agent.web import server


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


@pytest.mark.parametrize(
    ("method", "path", "target", "body", "expected"),
    [
        pytest.param("GET", "/api/health", "build_health_payload", _NO_BODY, (_ROOT,), id="health"),
        pytest.param("GET", "/api/config", "build_config_payload", _NO_BODY, (_ROOT,), id="config-get"),
        pytest.param("GET", "/api/chats", "build_chats_payload", _NO_BODY, (_ROOT,), id="chats"),
        pytest.param("GET", "/api/tools", "build_tools_payload", _NO_BODY, (), id="tools"),
        pytest.param("GET", "/api/runs", "_build_runs_payload", _NO_BODY, (_ROOT,), id="runs"),
        pytest.param("GET", "/api/files?path=src", "build_files_payload", _NO_BODY, (_ROOT, "src"), id="files"),
        pytest.param(
            "GET", "/api/file?path=README.md", "build_file_payload", _NO_BODY, (_ROOT, "README.md"), id="file"
        ),
        pytest.param(
            "GET",
            "/api/diff?path=a&snapshot=b",
            "build_diff_payload",
            _NO_BODY,
            (_ROOT, "a", "b"),
            id="diff",
        ),
        pytest.param(
            "GET", "/api/chats/chat_1", "build_chat_payload", _NO_BODY, (_ROOT, "chat_1"), id="chat-detail"
        ),
        pytest.param(
            "GET", "/api/runs/run_1", "_build_run_detail_payload", _NO_BODY, (_ROOT, "run_1"), id="run-detail"
        ),
        pytest.param("POST", "/api/chat/turn", "build_chat_turn_payload", {"value": "turn"}, (_ROOT, _BODY), id="turn"),
        pytest.param(
            "POST", "/api/chat/start", "build_chat_start_payload", {"value": "start"}, (_ROOT, _BODY), id="start"
        ),
        pytest.param(
            "POST", "/api/chat/approval", "build_chat_approval_payload", {"value": "approval"}, (_BODY,), id="approval"
        ),
        pytest.param(
            "POST", "/api/chat/rename", "build_chat_rename_payload", {"value": "rename"}, (_ROOT, _BODY), id="rename"
        ),
        pytest.param(
            "POST", "/api/chat/delete", "build_chat_delete_payload", {"value": "delete"}, (_ROOT, _BODY), id="delete"
        ),
        pytest.param("POST", "/api/config", "build_save_config_payload", {"value": "config"}, (_ROOT, _BODY), id="config-post"),
        pytest.param(
            "POST",
            "/api/snapshot/restore",
            "build_restore_snapshot_payload",
            {"value": "restore"},
            (_ROOT, _BODY),
            id="restore",
        ),
        pytest.param(
            "POST", "/api/file/save", "build_save_file_payload", {"value": "save"}, (_ROOT, _BODY), id="save"
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
    expected: tuple[object, ...],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def sentinel(*args: object, **kwargs: object) -> dict[str, str]:
        calls.append((args, kwargs))
        return {"target": target}

    monkeypatch.setattr(server, target, sentinel)

    status, _headers, response = _http_request(workspace, method, path, body)

    expected_args = tuple(workspace.resolve() if item is _ROOT else body if item is _BODY else item for item in expected)
    assert status == 200
    assert json.loads(response) == {"target": target}
    assert calls == [(expected_args, {})]


def test_workbench_sse_route_sends_headers_for_known_job(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[str, int, float]] = []
    monkeypatch.setattr(server, "_get_chat_job", lambda job_id: object())

    def events(job_id: str, *, after: int, timeout: float) -> dict[str, object]:
        calls.append((job_id, after, timeout))
        return {"job_id": job_id, "events": [], "done": True, "next": after}

    monkeypatch.setattr(server, "build_chat_events_payload", events)

    with _running_workbench(workspace) as (host, port):
        connection = HTTPConnection(host, port, timeout=2.0)
        try:
            connection.request("GET", "/api/chat/events?job_id=job_1")
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type") == "text/event-stream; charset=utf-8"
            response.close()
        finally:
            connection.close()

    assert calls == [("job_1", 0, 10.0)]


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


def test_chat_start_normalizes_message_and_empty_session_id(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(server, "_run_chat_job", lambda *_args: None)
    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()

    try:
        status, _headers, response = _http_request(
            workspace,
            "POST",
            "/api/chat/start",
            {"message": "  hi  ", "session_id": ""},
        )
        payload = json.loads(response)
        job = server._get_chat_job(payload["job_id"])

        assert status == 200
        assert job.message == "hi"
        assert payload["session_id"].startswith("chat_")
    finally:
        with server._CHAT_JOBS_LOCK:
            server._CHAT_JOBS.clear()


def test_chat_start_rejects_unsafe_session_id_before_llm(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    llm_called = threading.Event()

    def fail_llm(_config):
        llm_called.set()
        raise AssertionError("LLM must not be created for an unsafe session id")

    monkeypatch.setattr(server, "make_llm", fail_llm)
    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()

    try:
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
        with server._CHAT_JOBS_LOCK:
            assert not server._CHAT_JOBS
    finally:
        with server._CHAT_JOBS_LOCK:
            server._CHAT_JOBS.clear()


def test_build_chat_events_payload_prunes_finished_jobs_after_ttl(monkeypatch, tmp_path) -> None:
    old = server._ChatJob(
        job_id="job_old",
        workspace=tmp_path,
        session_id="chat_old",
        message="old",
    )
    old.done = True
    old.completed_at = 100.0
    active = server._ChatJob(
        job_id="job_active",
        workspace=tmp_path,
        session_id="chat_active",
        message="active",
    )

    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()
        server._CHAT_JOBS[old.job_id] = old
        server._CHAT_JOBS[active.job_id] = active

    monkeypatch.setattr(server.time, "monotonic", lambda: 100.0 + server.CHAT_JOB_TTL_SECONDS + 1.0)

    payload = server.build_chat_events_payload(active.job_id, timeout=0)

    assert payload["job_id"] == active.job_id
    with server._CHAT_JOBS_LOCK:
        assert old.job_id not in server._CHAT_JOBS
        assert active.job_id in server._CHAT_JOBS
        server._CHAT_JOBS.clear()


def test_config_update_accepts_openai_compat_provider(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = server.build_save_config_payload(
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

    payload = server.build_health_payload(workspace)

    assert payload["native_tools"] is False


def test_config_update_accepts_native_tools_boolean(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = server.build_save_config_payload(workspace, {"native_tools": True})

    assert payload["status"] == "ok"
    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    assert "native_tools = true" in config_text


def test_config_update_rejects_non_boolean_native_tools(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError):
        server.build_save_config_payload(workspace, {"native_tools": "yes"})


def test_chat_job_streams_tagged_model_chunks(monkeypatch, tmp_path) -> None:
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

    monkeypatch.setattr(server, "make_llm", lambda config: StreamingFake())

    started = server.build_chat_start_payload(workspace, {"message": "hi"})
    events: list[dict] = []
    after = 0
    for _ in range(50):
        payload = server.build_chat_events_payload(started["job_id"], after=after, timeout=5.0)
        events.extend(payload["events"])
        after = payload["next"]
        if payload["done"]:
            break
    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()

    chunk_events = [event for event in events if event.get("event") == "model_stream_chunk"]
    assert [(event["kind"], event["text"]) for event in chunk_events] == [
        ("thinking", "planning"),
        ("args", '{"final"'),
    ]
    assert any(event.get("event") == "final" for event in events)


def test_chat_job_batches_tiny_model_chunks(monkeypatch, tmp_path) -> None:
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

    monkeypatch.setattr(server, "make_llm", lambda config: StreamingFake())

    started = server.build_chat_start_payload(workspace, {"message": "hi"})
    events: list[dict] = []
    after = 0
    for _ in range(50):
        payload = server.build_chat_events_payload(started["job_id"], after=after, timeout=5.0)
        events.extend(payload["events"])
        after = payload["next"]
        if payload["done"]:
            break
    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()

    chunk_events = [event for event in events if event.get("event") == "model_stream_chunk"]
    assert "".join(event["text"] for event in chunk_events) == streamed
    assert [event["chunk_chars"] for event in chunk_events] == [len(event["text"]) for event in chunk_events]
    assert len(chunk_events) <= 3
