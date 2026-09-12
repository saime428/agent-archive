from __future__ import annotations

import gzip
import io
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

from agent import _user_store
from agent.config import AgentConfig
from agent.core.chat import ConversationState
from agent.core.run_lease import WorkspaceRunLease
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import ProviderError
from agent.web import chat_runtime
from agent.web import chats
from agent.web import server
from agent.web import settings
from agent.web.chat_runtime import ChatRuntime


_NO_BODY = object()
_ROOT = object()
_BODY = object()


@contextmanager
def _running_workbench(workspace: Path, *, mcp_runtime=None) -> Iterator[tuple[str, int]]:
    handler = (
        server.create_workbench_handler(workspace)
        if mcp_runtime is None
        else server.create_workbench_handler(workspace, mcp_runtime=mcp_runtime)
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
    *,
    mcp_runtime=None,
    request_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = None if body is _NO_BODY else body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    headers = {} if body is _NO_BODY else {"Content-Type": "application/json"}
    headers.update(request_headers or {})
    with _running_workbench(workspace, mcp_runtime=mcp_runtime) as (host, port):
        connection = HTTPConnection(host, port, timeout=2.0)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            return response.status, response_headers, response.read()
        finally:
            connection.close()


def test_workbench_rejects_untrusted_host_header(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(
        workspace,
        "GET",
        "/api/health",
        request_headers={"Host": "attacker.example"},
    )

    assert status == 403
    assert json.loads(response) == {"error": "Workbench only accepts loopback requests."}


def test_workbench_rejects_cross_origin_write(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(
        workspace,
        "POST",
        "/api/config",
        {"dry_run": True},
        request_headers={"Origin": "https://attacker.example"},
    )

    assert status == 403
    assert json.loads(response) == {"error": "Cross-origin Workbench writes are not allowed."}
    assert not (workspace / ".agent" / "config.toml").exists()


def test_workbench_rejects_simple_form_write_without_json_content_type(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(
        workspace,
        "POST",
        "/api/config",
        b'{"dry_run": true}',
        request_headers={"Content-Type": "text/plain"},
    )

    assert status == 400
    assert json.loads(response) == {"error": "Content-Type must be application/json."}
    assert not (workspace / ".agent" / "config.toml").exists()


def test_workbench_consumes_bounded_rejected_body_before_responding(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b'{"dry_run": true}'
    handler_type = server.create_workbench_handler(workspace)
    handler = handler_type.__new__(handler_type)
    handler.headers = {"Content-Length": str(len(payload)), "Content-Type": "text/plain"}
    handler.rfile = io.BytesIO(payload)

    with pytest.raises(ValueError, match="Content-Type"):
        handler._read_json_body()

    assert handler.rfile.read() == b""


def test_workbench_applies_security_headers_to_success_and_error_responses(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _status, headers, _response = _http_request(workspace, "GET", "/api/health")
    _missing_status, missing_headers, _missing_response = _http_request(workspace, "GET", "/missing")

    for response_headers in (headers, missing_headers):
        assert response_headers["x-content-type-options"] == "nosniff"
        assert response_headers["x-frame-options"] == "DENY"
        assert response_headers["referrer-policy"] == "no-referrer"
        csp = response_headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        script_src = next(part.strip() for part in csp.split(";") if part.strip().startswith("script-src"))
        assert script_src == "script-src 'self'"


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
            "GET",
            "/api/search?query=hello%20world",
            "build_search_payload",
            _NO_BODY,
            (_ROOT, "hello world"),
            {},
            id="search",
        ),
        pytest.param(
            "GET", "/api/file?path=README.md", "build_file_payload", _NO_BODY, (_ROOT, "README.md"), {}, id="file"
        ),
        pytest.param(
            "GET", "/api/git/status", "build_git_status_payload", _NO_BODY, (_ROOT,), {}, id="git-status"
        ),
        pytest.param(
            "GET",
            "/api/git/diff?path=src%2Fapp.py&area=staged",
            "build_git_diff_payload",
            _NO_BODY,
            (_ROOT, "src/app.py", "staged"),
            {},
            id="git-diff",
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
        pytest.param(
            "POST",
            "/api/chat/start",
            "runtime.start",
            {"message": "  hi  ", "session_id": "", "timeout_seconds": 30},
            (),
            {"message": "hi", "session_id": "", "timeout_seconds": 30},
            id="start",
        ),
        pytest.param(
            "POST",
            "/api/chat/cancel",
            "runtime.cancel",
            {"job_id": "job_0123456789ab"},
            ("job_0123456789ab",),
            {},
            id="cancel",
        ),
        pytest.param(
            "POST",
            "/api/chat/resume",
            "runtime.resume",
            {"job_id": "job_0123456789ab", "message": "  next  ", "timeout_seconds": 45},
            (),
            {"job_id": "job_0123456789ab", "message": "next", "timeout_seconds": 45},
            id="resume",
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

        def start(self, *, message: str, session_id: str | None, timeout_seconds=None) -> dict[str, str]:
            return sentinel(message=message, session_id=session_id, timeout_seconds=timeout_seconds)

        def cancel(self, job_id: str) -> dict[str, str]:
            return sentinel(job_id)

        def resume(self, *, job_id: str, message: str, timeout_seconds=None) -> dict[str, str]:
            return sentinel(job_id=job_id, message=message, timeout_seconds=timeout_seconds)

        def decide(self, *, job_id: str, approve: bool) -> dict[str, str]:
            return sentinel(job_id=job_id, approve=approve)

        @contextmanager
        def _reserve_session(self, _session_id: object):
            yield

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


def test_workbench_async_chat_path_borrows_the_injected_mcp_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    borrowed = object()
    seen: list[tuple[str, object]] = []

    class FakeChatRuntime:
        def __init__(self, _workspace: Path, *, mcp_runtime) -> None:
            seen.append(("async", mcp_runtime))

        def start(self, *, message: str, session_id: str | None, timeout_seconds=None) -> dict[str, object]:
            return {"status": "running", "job_id": "job_1", "session_id": session_id}

        @contextmanager
        def _reserve_session(self, _session_id: object):
            yield

    monkeypatch.setattr(server, "ChatRuntime", FakeChatRuntime)
    start_status, _headers, _response = _http_request(
        workspace,
        "POST",
        "/api/chat/start",
        {"message": "async"},
        mcp_runtime=borrowed,
    )

    assert start_status == 200
    assert seen == [("async", borrowed)]


@pytest.mark.parametrize("stage", ["config", "initialize", "discovery"])
def test_async_chat_job_reports_mcp_error_before_model_call(tmp_path, stage: str) -> None:
    model_calls = 0

    class NoCallLLM:
        def chat(self, _messages, *, temperature=None):
            nonlocal model_calls
            model_calls += 1
            return _done_response()

    class FailingRuntime:
        def discover_tools(self):
            raise server.McpRuntimeError(
                stage=stage,
                server_id="local",
                message=f"safe {stage} failure",
            )

    runtime = ChatRuntime(
        tmp_path,
        llm_factory=lambda _config: NoCallLLM(),
        mcp_runtime=FailingRuntime(),
    )
    started = runtime.start(message="fail before model", session_id=None)
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    errors = [event for event in complete["events"] if event["event"] == "error"]

    assert len(errors) == 1
    assert errors[0]["error"] == (
        f"MCP {stage} failed for server 'local': safe {stage} failure"
    )
    assert model_calls == 0


def test_chat_runtime_final_event_projects_repaired_turn(tmp_path) -> None:
    class RepairThenDoneLLM:
        def __init__(self) -> None:
            self.index = 0

        def chat(self, _messages, *, temperature=None):
            self.index += 1
            if self.index == 1:
                return "{not-json"
            return _done_response("repaired")

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: RepairThenDoneLLM())
    started = runtime.start(message="repair", session_id="chat_repair")
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    final = next(event for event in complete["events"] if event["event"] == "final")

    assert final["display_status"] == "completed"
    assert final["repair_count"] == 1
    assert final["has_repair_noise"] is True
    assert final["final"] == "repaired"
    assert "invalid_model_response" not in final["thinking_text"]


def test_chat_runtime_final_event_projects_ask_user(tmp_path) -> None:
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Ask.",
                "action": {
                    "name": "ask_user",
                    "args": {"question": "Please describe the task."},
                },
            }
        ]
    )
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: llm)
    started = runtime.start(message="ask", session_id="chat_ask")
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    final = next(event for event in complete["events"] if event["event"] == "final")

    assert final["completed"] is False
    assert final["terminal_reason"] == "ask_user"
    assert final["display_status"] == "ask_user"
    assert final["final"] == "Please describe the task."


def test_chat_runtime_final_event_includes_public_action_message(tmp_path) -> None:
    llm = FakeLLMClient(
        actions=[
            {
                "message": "Check the workspace files first.",
                "action": {"name": "list_dir", "args": {"path": ".", "max_entries": 10}},
            },
            _done_response("Checked files."),
        ]
    )
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: llm)
    started = runtime.start(message="inspect", session_id="chat_process")
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    final = next(event for event in complete["events"] if event["event"] == "final")

    assert "Check the workspace files first." in final["thinking_text"]
    assert "invalid_model_response" not in final["thinking_text"]


@pytest.mark.parametrize(
    ("phase", "expected_error"),
    [
        ("normal", None),
        ("keyboard", None),
        ("terminal_create", "terminal create failed"),
        ("handler", "handler failed"),
        ("bind", "bind failed"),
        ("timer", "timer failed"),
        ("serve", "serve failed"),
        ("server_close", "server close failed"),
        ("terminal_close", "terminal close failed"),
        ("mcp_close", "mcp close failed"),
    ],
)
def test_serve_workbench_closes_owned_mcp_runtime_on_every_exit_path(
    monkeypatch,
    tmp_path,
    phase: str,
    expected_error: str | None,
) -> None:
    events: list[str] = []

    class OwnedMcpRuntime:
        def close(self) -> None:
            events.append("mcp_close")
            if phase == "mcp_close":
                raise RuntimeError("mcp close failed")

    class OwnedTerminalRuntime:
        def close(self) -> None:
            events.append("terminal_close")
            if phase == "terminal_close":
                raise RuntimeError("terminal close failed")

    owned_mcp = OwnedMcpRuntime()
    owned_terminal = OwnedTerminalRuntime()

    def make_mcp_runtime(root: Path):
        assert root == tmp_path.resolve()
        events.append("mcp_create")
        return owned_mcp

    def make_terminal_runtime(root: Path):
        assert root == tmp_path.resolve()
        events.append("terminal_create")
        if phase == "terminal_create":
            raise RuntimeError("terminal create failed")
        return owned_terminal

    def make_handler(root: Path, *, mcp_runtime, terminal_runtime):
        assert root == tmp_path.resolve()
        assert mcp_runtime is owned_mcp
        assert terminal_runtime is owned_terminal
        events.append("handler")
        if phase == "handler":
            raise RuntimeError("handler failed")
        return object()

    class FakeServer:
        def __init__(self, _address, _handler) -> None:
            events.append("bind")
            if phase == "bind":
                raise OSError("bind failed")

        def serve_forever(self) -> None:
            events.append("serve")
            if phase == "keyboard":
                raise KeyboardInterrupt
            if phase == "serve":
                raise RuntimeError("serve failed")

        def server_close(self) -> None:
            events.append("server_close")
            if phase == "server_close":
                raise RuntimeError("server close failed")

    def make_timer(*_args, **_kwargs):
        def start() -> None:
            events.append("timer")
            if phase == "timer":
                raise RuntimeError("timer failed")

        return SimpleNamespace(start=start)

    monkeypatch.setattr(server, "McpStdioRuntime", make_mcp_runtime)
    monkeypatch.setattr(server, "TerminalRuntime", make_terminal_runtime)
    monkeypatch.setattr(server, "create_workbench_handler", make_handler)
    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(server.threading, "Timer", make_timer)

    if expected_error is None:
        server.serve_workbench(
            workspace=tmp_path,
            port=8765,
            open_browser=False,
        )
    else:
        with pytest.raises((OSError, RuntimeError), match=expected_error):
            server.serve_workbench(
                workspace=tmp_path,
                port=8765,
                open_browser=phase == "timer",
            )

    assert events.count("mcp_close") == 1
    assert events.count("terminal_close") == (0 if phase == "terminal_create" else 1)
    if "server_close" in events:
        assert events.index("server_close") < events.index("terminal_close")
    if "terminal_close" in events:
        assert events.index("terminal_close") < events.index("mcp_close")
    assert events[-1] == "mcp_close"


def test_serve_workbench_rejects_non_loopback_bind_before_runtime_start(monkeypatch, tmp_path) -> None:
    def fail_runtime(_root: Path):
        raise AssertionError("runtime must not start for a non-loopback bind")

    monkeypatch.setattr(server, "McpStdioRuntime", fail_runtime)

    with pytest.raises(ValueError, match="loopback"):
        server.serve_workbench(workspace=tmp_path, host="0.0.0.0")


def test_serve_workbench_uses_daemon_request_threads(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class Runtime:
        def close(self) -> None:
            pass

    class FakeServer:
        daemon_threads = False

        def __init__(self, _address, _handler) -> None:
            captured["server"] = self

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(server, "McpStdioRuntime", lambda _root: Runtime())
    monkeypatch.setattr(server, "TerminalRuntime", lambda _root: Runtime())
    monkeypatch.setattr(
        server,
        "create_workbench_handler",
        lambda _root, *, mcp_runtime, terminal_runtime: object(),
    )
    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)

    server.serve_workbench(workspace=tmp_path)

    assert captured["server"].daemon_threads is True


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


def test_workbench_sse_route_starts_from_requested_cursor(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[str, int, float]] = []
    event = {"event": "final", "sequence": 2, "final": "ok"}

    class FakeRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        def poll(self, job_id: str, *, after: int, timeout: float) -> dict[str, object]:
            calls.append((job_id, after, timeout))
            return {"job_id": job_id, "events": [event], "done": True, "next": 3}

    monkeypatch.setattr(server, "ChatRuntime", FakeRuntime)

    status, _headers, response = _http_request(
        workspace,
        "GET",
        "/api/chat/events?job_id=job_0123456789ab&after=2",
    )

    assert status == 200
    assert b"id: 2" in response
    assert calls == [("job_0123456789ab", 2, 0)]


@pytest.mark.parametrize("after", ["-1", "nope", "1.5"])
def test_workbench_sse_route_rejects_invalid_cursor(tmp_path, after: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, _headers, response = _http_request(
        workspace,
        "GET",
        f"/api/chat/events?job_id=job_0123456789ab&after={after}",
    )

    assert status == 400
    assert json.loads(response) == {"error": "after must be a non-negative integer."}


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
    assert json.loads(response) == {"error": "chat job id is invalid."}


@pytest.mark.parametrize("after", [0, 7])
def test_workbench_sse_route_terminates_wellformed_unknown_job_with_failed_event(tmp_path, after: int) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, headers, response = _http_request(
        workspace,
        "GET",
        f"/api/chat/events?job_id=job_0123456789ab&after={after}",
    )

    assert status == 200
    assert headers["content-type"] == "text/event-stream; charset=utf-8"
    assert headers["connection"] == "close"
    body = response.decode("utf-8")
    assert f"id: {after}\nevent: failed\n" in body
    data = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])
    assert data["event"] == "failed"
    assert data["sequence"] == after
    assert data["elapsed_ms"] == 0
    assert data["run_id"] == ""
    assert data["error"]
    assert body.count("\n\n") == 1


def test_workbench_static_fallback_and_unknown_post(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    status, headers, _response = _http_request(workspace, "GET", "/")
    unknown_status, _unknown_headers, unknown_response = _http_request(workspace, "POST", "/api/unknown")

    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert unknown_status == 404
    assert json.loads(unknown_response) == {"error": "Unknown endpoint: /api/unknown"}


def test_workbench_serves_nested_directory_index(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    static_root = tmp_path / "static"
    (static_root / "preview").mkdir(parents=True)
    (static_root / "index.html").write_text("legacy", encoding="utf-8")
    (static_root / "preview" / "index.html").write_text("preview", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_ROOT", static_root.resolve())

    root_status, _root_headers, root_response = _http_request(workspace, "GET", "/")
    preview_status, _preview_headers, preview_response = _http_request(workspace, "GET", "/preview/")
    missing_status, _missing_headers, _missing_response = _http_request(workspace, "GET", "/preview/missing/")

    assert (root_status, root_response) == (200, b"preview")
    assert (preview_status, preview_response) == (200, b"preview")
    assert missing_status == 404


def _entrypoint_static_root(tmp_path: Path) -> Path:
    static_root = tmp_path / "static"
    (static_root / "preview" / "assets").mkdir(parents=True)
    (static_root / "index.html").write_text("legacy", encoding="utf-8")
    (static_root / "preview" / "index.html").write_text("preview", encoding="utf-8")
    (static_root / "preview" / "assets" / "app.js").write_text("export const app = 1;\n", encoding="utf-8")
    return static_root.resolve()


def test_workbench_serves_react_entrypoints_and_retires_legacy(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(server, "STATIC_ROOT", _entrypoint_static_root(tmp_path))

    root_status, _root_headers, root_response = _http_request(workspace, "GET", "/")
    preview_status, _preview_headers, preview_response = _http_request(workspace, "GET", "/preview/")
    legacy_status, _legacy_headers, _legacy_response = _http_request(workspace, "GET", "/legacy/")
    unknown_status, _unknown_headers, _unknown_response = _http_request(workspace, "GET", "/missing/")

    assert (root_status, root_response) == (200, b"preview")
    assert (preview_status, preview_response) == (200, b"preview")
    assert legacy_status == 404
    assert unknown_status == 404


def test_workbench_normalizes_stable_entrypoint_aliases(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(server, "STATIC_ROOT", _entrypoint_static_root(tmp_path))

    preview_status, preview_headers, preview_response = _http_request(
        workspace, "GET", "/preview?from=bookmark"
    )
    legacy_status, _legacy_headers, _legacy_response = _http_request(
        workspace, "GET", "/legacy?from=rollback"
    )
    bare_status, bare_headers, _bare_response = _http_request(workspace, "GET", "/preview")

    assert preview_status == 308
    assert preview_headers["location"] == "/preview/?from=bookmark"
    assert preview_headers["content-length"] == "0"
    assert preview_response == b""
    assert legacy_status == 404
    assert bare_status == 308
    assert bare_headers["location"] == "/preview/"


def test_workbench_only_disables_caching_for_html_entrypoints(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(server, "STATIC_ROOT", _entrypoint_static_root(tmp_path))

    _root_status, root_headers, _root_response = _http_request(workspace, "GET", "/")
    _preview_status, preview_headers, _preview_response = _http_request(workspace, "GET", "/preview/")
    asset_status, asset_headers, _asset_response = _http_request(
        workspace, "GET", "/preview/assets/app.js"
    )

    assert root_headers["cache-control"] == "no-store"
    assert preview_headers["cache-control"] == "no-store"
    assert asset_status == 200
    assert "cache-control" not in asset_headers


def test_workbench_serves_staged_preview_assets_byte_for_byte(tmp_path) -> None:
    preview_root = server.STATIC_ROOT / "preview"
    assets = sorted(path for path in preview_root.rglob("*") if path.is_file())
    assert assets, "Staged preview assets are missing. Run npm run build:preview from frontend/."

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with _running_workbench(workspace) as (host, port):
        connection = HTTPConnection(host, port, timeout=2.0)
        try:
            for asset in assets:
                url = "/" + asset.relative_to(server.STATIC_ROOT).as_posix()
                connection.request("GET", url, headers={"Accept-Encoding": "identity"})
                response = connection.getresponse()
                assert response.status == 200, url
                assert response.read() == asset.read_bytes(), url
        finally:
            connection.close()


def test_workbench_returns_404_for_missing_preview_assets(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    static_root = tmp_path / "static"
    static_root.mkdir()
    monkeypatch.setattr(server, "STATIC_ROOT", static_root.resolve())

    status, _headers, _response = _http_request(workspace, "GET", "/preview/")

    assert status == 404


def test_workbench_retires_legacy_assets_and_sync_chat_endpoint(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    legacy_status, _legacy_headers, _legacy_response = _http_request(workspace, "GET", "/legacy/")
    asset_status, _asset_headers, _asset_response = _http_request(workspace, "GET", "/assets/app.js")
    turn_status, _turn_headers, turn_response = _http_request(
        workspace,
        "POST",
        "/api/chat/turn",
        {"message": "retired"},
    )

    assert legacy_status == 404
    assert asset_status == 404
    assert turn_status == 404
    assert json.loads(turn_response) == {"error": "Unknown endpoint: /api/chat/turn"}


def test_workbench_negotiates_gzip_for_large_static_assets(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    static_root = tmp_path / "static"
    static_root.mkdir()
    source = b"const payload = 'spatial';\n" * 100
    (static_root / "app.js").write_bytes(source)
    monkeypatch.setattr(server, "STATIC_ROOT", static_root.resolve())

    status, headers, response = _http_request(
        workspace,
        "GET",
        "/app.js",
        request_headers={"Accept-Encoding": "br, gzip"},
    )

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert headers["vary"] == "Accept-Encoding"
    assert int(headers["content-length"]) == len(response)
    assert gzip.decompress(response) == source

    plain_status, plain_headers, plain_response = _http_request(
        workspace,
        "GET",
        "/app.js",
        request_headers={"Accept-Encoding": "gzip;q=0, *;q=1"},
    )

    assert plain_status == 200
    assert "content-encoding" not in plain_headers
    assert plain_headers["vary"] == "Accept-Encoding"
    assert plain_response == source


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        pytest.param("/api/config", _NO_BODY, "JSON body is required.", id="missing-body"),
        pytest.param("/api/chat/start", {"message": " "}, "message is required.", id="empty-message"),
        pytest.param(
            "/api/chat/start",
            {"message": "hi", "timeout_seconds": True},
            "timeout_seconds must be an integer from 1 to 3600.",
            id="start-timeout-bool",
        ),
        pytest.param(
            "/api/chat/start",
            {"message": "hi", "timeout_seconds": 3601},
            "timeout_seconds must be an integer from 1 to 3600.",
            id="start-timeout-range",
        ),
        pytest.param(
            "/api/chat/cancel",
            {},
            "job_id is required.",
            id="cancel-job",
        ),
        pytest.param(
            "/api/chat/resume",
            {"job_id": "job_0123456789ab", "message": " "},
            "message is required.",
            id="resume-message",
        ),
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


@pytest.mark.parametrize("disconnect_error", [BrokenPipeError, ConnectionAbortedError])
def test_workbench_ignores_client_disconnect_at_handler_boundary(
    monkeypatch, tmp_path, disconnect_error: type[OSError]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    handler_type = server.create_workbench_handler(workspace)
    handler = object.__new__(handler_type)

    def disconnect(_handler) -> None:
        raise disconnect_error("client disconnected")

    monkeypatch.setattr(server.BaseHTTPRequestHandler, "handle", disconnect)

    handler.handle()


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
def test_chat_runtime_reloads_pruned_jobs_from_durable_store(tmp_path, entry: str) -> None:
    now = [100.0]
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient(), clock=lambda: now[0], job_ttl=10.0)
    started = runtime.start(message="old", session_id=None)
    _wait_for_runtime_done(runtime, started["job_id"])
    now[0] += 11.0

    if entry == "start":
        new_job = runtime.start(message="new", session_id=None)
        _wait_for_runtime_done(runtime, new_job["job_id"])

    if entry == "decide":
        with pytest.raises(ValueError, match="chat job is already finished"):
            runtime.decide(job_id=started["job_id"], approve=True)
    else:
        restored = runtime.poll(started["job_id"], timeout=0)
        assert restored["done"] is True
        assert restored["status"] == "completed"
        assert restored["events"]


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


@pytest.mark.parametrize("session_id", [None, "chat_requested"])
def test_chat_runtime_makes_new_session_readable_before_async_turn_finishes(tmp_path, session_id: str | None) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: BlockingLLM())
    started = runtime.start(message="wait", session_id=session_id)
    assert entered.wait(1.0)

    try:
        payload = chats.build_chat_payload(tmp_path, started["session_id"])
        assert payload["turn_count"] == 0
    finally:
        release.set()
        _wait_for_runtime_done(runtime, started["job_id"])


def test_chat_runtime_publishes_durable_job_before_start_returns(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: BlockingLLM())
    started = runtime.start(message="wait", session_id="chat_durable", timeout_seconds=30)
    assert entered.wait(1.0)
    root = tmp_path / ".agent" / "chat-jobs"
    metadata_path = root / f"{started['job_id']}.json"
    events_path = root / f"{started['job_id']}.events.jsonl"
    active_path = root / "active.json"

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    active = json.loads(active_path.read_text(encoding="utf-8"))

    assert started == {
        "status": "running",
        "job_id": metadata["job_id"],
        "session_id": "chat_durable",
        "run_id": metadata["run_id"],
    }
    assert metadata["status"] == "running"
    assert metadata["timeout_seconds"] == 30
    assert metadata["message"] == "wait"
    assert metadata["resumed_from_job_id"] is None
    assert events[0]["event"] == "chat_started"
    assert events[0]["sequence"] == 0
    assert active == {"version": 1, "job_id": started["job_id"]}
    assert (tmp_path / ".agent" / "chats" / "chat_durable" / "session.json").is_file()

    release.set()
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    assert complete["done"] is True
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert not active_path.exists()


def test_chat_runtime_uses_one_workspace_lease_across_instances(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()
    second_called = threading.Event()

    class BlockingLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    first = ChatRuntime(tmp_path, llm_factory=lambda _config: BlockingLLM())
    second = ChatRuntime(
        tmp_path,
        llm_factory=lambda _config: (second_called.set(), FakeLLMClient())[1],
    )
    started = first.start(message="first", session_id="chat_first")
    assert entered.wait(1.0)

    with pytest.raises(ValueError, match="Workspace already has an active Agent turn"):
        second.start(message="second", session_id="chat_second")
    with pytest.raises(ValueError, match="already has an active turn"):
        with second._reserve_session("chat_first"):
            pass
    with second._reserve_session("chat_second"):
        pass
    assert not second_called.is_set()

    release.set()
    _wait_for_runtime_done(first, started["job_id"])
    restarted = second.start(message="after release", session_id="chat_second")
    _wait_for_runtime_done(second, restarted["job_id"])


def test_chat_runtime_rejects_a_second_active_turn_for_the_same_session(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingLLM:
        def chat(self, _messages, *, temperature=None):
            entered.set()
            assert release.wait(2.0)
            return _done_response()

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: BlockingLLM())
    started = runtime.start(message="first", session_id="chat_shared")
    assert entered.wait(1.0)

    with pytest.raises(ValueError, match="already has an active turn"):
        runtime.start(message="second", session_id="chat_shared")
    with pytest.raises(ValueError, match="already has an active turn"):
        with runtime._reserve_session("chat_shared"):
            pass

    release.set()
    _wait_for_runtime_done(runtime, started["job_id"])
    with runtime._reserve_session("chat_shared"):
        pass


def test_chat_runtime_claims_existing_session_before_loading_state(monkeypatch, tmp_path) -> None:
    original_load = chat_runtime.chats.load_or_create_chat_state
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())

    def load_while_claimed(root: Path, session_id: str | None):
        with pytest.raises(ValueError, match="already has an active turn"):
            with runtime._reserve_session(session_id):
                pass
        return original_load(root, session_id)

    monkeypatch.setattr(chat_runtime.chats, "load_or_create_chat_state", load_while_claimed)

    started = runtime.start(message="first", session_id="chat_claimed")

    _wait_for_runtime_done(runtime, started["job_id"])


def test_chat_runtime_does_not_release_another_job_on_generated_session_collision(monkeypatch, tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    monkeypatch.setattr(
        chat_runtime.chats,
        "load_or_create_chat_state",
        lambda _root, _session_id: SimpleNamespace(session_id="chat_busy"),
    )

    with runtime._reserve_session("chat_busy"):
        with pytest.raises(ValueError, match="already has an active turn"):
            runtime.start(message="collision", session_id=None)
        with pytest.raises(ValueError, match="already has an active turn"):
            with runtime._reserve_session("chat_busy"):
                pass


@pytest.mark.parametrize("path", ["/api/chat/rename", "/api/chat/delete"])
def test_workbench_blocks_chat_mutation_while_session_is_active(monkeypatch, tmp_path, path: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class ActiveRuntime:
        def __init__(self, _workspace: Path) -> None:
            pass

        @contextmanager
        def _reserve_session(self, session_id: object):
            assert session_id == "chat_busy"
            raise ValueError("Chat session chat_busy already has an active turn.")
            yield

    monkeypatch.setattr(server, "ChatRuntime", ActiveRuntime)
    body = {"session_id": "chat_busy"}
    if path.endswith("rename"):
        body["title"] = "new"

    status, _headers, response = _http_request(workspace, "POST", path, body)

    assert status == 400
    assert "already has an active turn" in json.loads(response)["error"]


def test_chat_runtime_registry_is_instance_local(tmp_path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = ChatRuntime(first_root, llm_factory=lambda _config: FakeLLMClient())
    second = ChatRuntime(second_root, llm_factory=lambda _config: FakeLLMClient())
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


def test_chat_runtime_reloads_events_and_ignores_only_partial_tail(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    started = runtime.start(message="hi", session_id=None)
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    events_path = tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"event":"partial"')

    restored = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient()).poll(
        started["job_id"],
        timeout=0,
    )

    assert restored["done"] is True
    assert restored["events"] == complete["events"]


def test_chat_runtime_redacts_durable_message_and_events(tmp_path) -> None:
    secret = "sk-test-secret-123456"
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    started = runtime.start(message=f"remember {secret}", session_id="chat_durable_secret")
    _wait_for_runtime_done(runtime, started["job_id"])
    root = tmp_path / ".agent"

    durable_text = "\n".join(
        [
            (root / "chat-jobs" / f"{started['job_id']}.json").read_text(encoding="utf-8"),
            (root / "chat-jobs" / f"{started['job_id']}.events.jsonl").read_text(encoding="utf-8"),
            (root / "chats" / "chat_durable_secret" / "session.json").read_text(encoding="utf-8"),
        ]
    )
    assert secret not in durable_text
    assert "[REDACTED]" in durable_text


@pytest.mark.parametrize("corruption", ["invalid_json", "sequence_gap"])
def test_chat_runtime_rejects_complete_event_corruption(tmp_path, corruption: str) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    started = runtime.start(message="hi", session_id=None)
    _wait_for_runtime_done(runtime, started["job_id"])
    events_path = tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    if corruption == "invalid_json":
        lines.insert(1, "not-json")
    else:
        event = json.loads(lines[1])
        event["sequence"] = 99
        lines[1] = json.dumps(event)
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    restored = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    with pytest.raises(ValueError, match="event"):
        restored.poll(started["job_id"], timeout=0)


def test_chat_runtime_rejects_redirected_event_file(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    started = runtime.start(message="hi", session_id=None)
    _wait_for_runtime_done(runtime, started["job_id"])
    events_path = tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.events.jsonl"
    target = tmp_path / "redirected-events.jsonl"
    events_path.replace(target)
    try:
        events_path.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        target.replace(events_path)
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    restored = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    with pytest.raises(ValueError, match="regular file"):
        restored.poll(started["job_id"], timeout=0)


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
    assert approval["expires_in_ms"] == int(chat_runtime.APPROVAL_WAIT_TIMEOUT_SECONDS * 1000)
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


def test_chat_runtime_cancel_is_idempotent_and_wakes_approval(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: _write_llm())
    started = runtime.start(message="write notes", session_id="chat_cancel", timeout_seconds=30)
    _wait_for_runtime_event(runtime, started["job_id"], "approval_required")

    first = runtime.cancel(started["job_id"])
    second = runtime.cancel(started["job_id"])
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    names = [event["event"] for event in complete["events"]]

    assert first["status"] in {"cancel_requested", "cancelled"}
    assert second["status"] in {"cancel_requested", "cancelled"}
    assert names.count("cancelled") == 1
    assert "final" not in names
    assert not (tmp_path / "notes.txt").exists()
    metadata = json.loads(
        (tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "cancelled"
    turn = chats.build_chat_payload(tmp_path, "chat_cancel")["turns"][-1]
    assert turn["terminal_reason"] == "cancelled"
    assert turn["job_id"] == started["job_id"]


def test_chat_runtime_run_timeout_is_distinct_from_approval_timeout(tmp_path) -> None:
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: _write_llm())
    started = runtime.start(message="write notes", session_id="chat_timeout", timeout_seconds=1)
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    names = [event["event"] for event in complete["events"]]

    assert complete["status"] == "timed_out"
    assert names.count("timed_out") == 1
    assert "approval_timed_out" not in names
    assert "final" not in names
    assert not (tmp_path / "notes.txt").exists()
    metadata = json.loads(
        (tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "timed_out"
    turn = chats.build_chat_payload(tmp_path, "chat_timeout")["turns"][-1]
    assert turn["terminal_reason"] == "timed_out"


def test_chat_runtime_resume_uses_only_the_new_message(tmp_path) -> None:
    class OldLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, _messages, *, temperature=None):
            self.calls += 1
            return {
                "message": "Write.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "must-not-exist.txt", "content": "old\n", "create_parents": False},
                },
            }

    class NewLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.messages = None

        def chat(self, messages, *, temperature=None):
            self.calls += 1
            self.messages = messages
            return _done_response("resumed")

    old_llm = OldLLM()
    new_llm = NewLLM()
    clients = iter([old_llm, new_llm])
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: next(clients))
    old = runtime.start(message="old side effect", session_id="chat_resume")
    _wait_for_runtime_event(runtime, old["job_id"], "approval_required")
    runtime.cancel(old["job_id"])
    _wait_for_runtime_done(runtime, old["job_id"])

    resumed = runtime.resume(job_id=old["job_id"], message="new safe message", timeout_seconds=30)
    complete = _wait_for_runtime_done(runtime, resumed["job_id"])

    assert complete["status"] == "completed"
    assert old_llm.calls == 1
    assert new_llm.calls == 1
    assert new_llm.messages[-1] == {"role": "user", "content": "new safe message"}
    assert not (tmp_path / "must-not-exist.txt").exists()
    metadata = json.loads(
        (tmp_path / ".agent" / "chat-jobs" / f"{resumed['job_id']}.json").read_text(encoding="utf-8")
    )
    assert metadata["resumed_from_job_id"] == old["job_id"]
    turns = chats.build_chat_payload(tmp_path, "chat_resume")["turns"]
    assert turns[-1]["resumed_from_job_id"] == old["job_id"]


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
    with pytest.raises(ValueError, match=r"chat approval has expired\."):
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
    _wait_for_runtime_event(runtime, started["job_id"], "failed")
    complete = _wait_for_runtime_done(runtime, started["job_id"])
    errors = [event["error"] for event in complete["events"] if event["event"] == "error"]
    failed = [event for event in complete["events"] if event["event"] == "failed"]

    assert errors == [f"{failure} exploded"]
    assert len(failed) == 1
    assert complete["done"] is True
    assert complete["status"] == "failed"
    metadata = json.loads(
        (tmp_path / ".agent" / "chat-jobs" / f"{started['job_id']}.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "failed"
    turn = chats.build_chat_payload(tmp_path, started["session_id"])["turns"][-1]
    assert turn["terminal_reason"] == "failed"
    assert turn["job_id"] == started["job_id"]
    summary = tmp_path / ".agent" / "runs" / started["run_id"] / "summary.md"
    assert "- terminal_reason: failed" in summary.read_text(encoding="utf-8")
    assert not (tmp_path / ".agent" / "chat-jobs" / "active.json").exists()


def test_chat_runtime_keeps_provider_failure_audit_and_marks_job_failed(tmp_path) -> None:
    class WriteThenFailLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, _messages, *, temperature=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "message": "Write.",
                    "action": {
                        "name": "write_file",
                        "args": {"path": "notes.txt", "content": "audit\n", "create_parents": False},
                    },
                }
            raise ProviderError("provider secret sk-web-secret")

    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: WriteThenFailLLM())
    started = runtime.start(message="write then fail", session_id=None)
    _wait_for_runtime_event(runtime, started["job_id"], "approval_required")
    runtime.decide(job_id=started["job_id"], approve=True)
    complete = _wait_for_runtime_done(runtime, started["job_id"])

    assert complete["status"] == "failed"
    assert [event["event"] for event in complete["events"]][-1] == "failed"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "audit\n"
    run_dir = tmp_path / ".agent" / "runs" / started["run_id"]
    assert len((run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "- action: provider_error" in summary
    assert "- completed: false" in summary
    assert "sk-web-secret" not in summary
    turn = chats.build_chat_payload(tmp_path, started["session_id"])["turns"][-1]
    assert turn["terminal_reason"] == "failed"


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
    root = tmp_path / ".agent" / "chat-jobs"
    assert not (root / "job_deadbeefcafe.json").exists()
    assert not (root / "job_deadbeefcafe.events.jsonl").exists()
    assert not (root / "active.json").exists()
    with WorkspaceRunLease.acquire(tmp_path, owner={"kind": "test"}):
        pass


def test_chat_runtime_rolls_back_partial_persistence_failure(monkeypatch, tmp_path) -> None:
    real_replace = _user_store.atomic_replace_json

    def fail_active(root, target, value, *, max_bytes=None):
        if target.name == "active.json":
            raise _user_store.UserStoreError("forced active failure")
        return real_replace(root, target, value, max_bytes=max_bytes)

    monkeypatch.setattr(chat_runtime.uuid, "uuid4", lambda: SimpleNamespace(hex="feedfacecafe0000"))
    monkeypatch.setattr(_user_store, "atomic_replace_json", fail_active)
    runtime = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())

    with pytest.raises(chat_runtime.ChatJobStoreError, match="durable chat job"):
        runtime.start(message="hi", session_id=None)

    root = tmp_path / ".agent" / "chat-jobs"
    assert not (root / "job_feedfacecafe.json").exists()
    assert not (root / "job_feedfacecafe.events.jsonl").exists()
    assert not (root / "active.json").exists()
    with WorkspaceRunLease.acquire(tmp_path, owner={"kind": "test"}):
        pass


def test_chat_runtime_recovers_interrupted_job_once(tmp_path) -> None:
    session_id = "chat_interrupted"
    job_id = "job_0123456789ab"
    run_id = "run_20260725_000000_000001"
    state = ConversationState.create(tmp_path, session_id=session_id)
    state.save(AgentConfig())
    root = tmp_path / ".agent" / "chat-jobs"
    root.mkdir()
    metadata = {
        "version": 1,
        "job_id": job_id,
        "session_id": session_id,
        "run_id": run_id,
        "status": "running",
        "started_at": "2026-07-25T00:00:00+00:00",
        "completed_at": None,
        "timeout_seconds": 30,
        "resumed_from_job_id": None,
        "message": "recover me",
    }
    (root / f"{job_id}.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    (root / f"{job_id}.events.jsonl").write_text(
        json.dumps({"event": "chat_started", "session_id": session_id, "run_id": run_id, "sequence": 0, "elapsed_ms": 0})
        + '\n{"event":"partial"',
        encoding="utf-8",
    )
    (root / "active.json").write_text(json.dumps({"version": 1, "job_id": job_id}) + "\n", encoding="utf-8")

    first = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    recovered = first.poll(job_id, timeout=0)
    second = ChatRuntime(tmp_path, llm_factory=lambda _config: FakeLLMClient())
    recovered_again = second.poll(job_id, timeout=0)

    assert recovered["done"] is True
    assert recovered["status"] == "interrupted"
    assert [event["event"] for event in recovered["events"]].count("interrupted") == 1
    assert recovered_again["events"] == recovered["events"]
    assert not (root / "active.json").exists()
    turn = chats.build_chat_payload(tmp_path, session_id)["turns"][-1]
    assert turn["terminal_reason"] == "interrupted"
    assert turn["job_id"] == job_id
    summary = tmp_path / ".agent" / "runs" / run_id / "summary.md"
    assert "- terminal_reason: interrupted" in summary.read_text(encoding="utf-8")


def test_chat_runtime_public_surface_is_start_poll_decide_only() -> None:
    public = {name for name in vars(ChatRuntime) if not name.startswith("_")}
    assert public == {"start", "poll", "decide", "cancel", "resume"}
