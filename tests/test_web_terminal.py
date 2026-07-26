from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent.config import load_config
from agent.config_write import save_project_config
from agent.policy.sandbox import SandboxError
from agent.web import server
from agent.web.terminal import MAX_ARG_CHARS, MAX_ARGV_ITEMS, MAX_INPUT_BYTES, TerminalRuntime


def _enable_terminal(workspace: Path) -> None:
    save_project_config(workspace, {"terminal_enabled": True})


def _wait_for(
    runtime: TerminalRuntime,
    terminal_id: str,
    *,
    status: set[str] | None = None,
    text: str | None = None,
    timeout: float = 3.0,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    deadline = time.monotonic() + timeout
    after = 0
    events: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        payload = runtime.snapshot(terminal_id=terminal_id, after=after, timeout=0.1)
        batch = payload["events"]
        assert isinstance(batch, list)
        events.extend(batch)
        after = int(payload["next"])
        joined = "\n".join(
            "".join(str(event["text"]) for event in events if event["stream"] == stream)
            for stream in {str(event["stream"]) for event in events}
        )
        if (status is None or payload["status"] in status) and (text is None or text in joined):
            return payload, events
    raise AssertionError(f"terminal did not reach status={status!r} text={text!r}")


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_exit(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} did not exit")


def _terminate_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
            if handle:
                try:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def test_terminal_config_defaults_disabled_and_can_be_explicitly_enabled(tmp_path: Path) -> None:
    config, _diagnostics = load_config(tmp_path)
    assert config.terminal_enabled is False

    _enable_terminal(tmp_path)

    config, _diagnostics = load_config(tmp_path)
    assert config.terminal_enabled is True


def test_terminal_rejects_start_while_disabled_shell_wrappers_and_external_cwd(tmp_path: Path) -> None:
    runtime = TerminalRuntime(tmp_path)
    try:
        with pytest.raises(ValueError, match="disabled"):
            runtime.start(argv=[sys.executable, "-c", "print('no')"], cwd=".", timeout_seconds=10)

        _enable_terminal(tmp_path)
        with pytest.raises(ValueError, match="Shell wrapper commands are not supported"):
            runtime.start(argv=["sh", "-c", "echo unsafe"], cwd=".", timeout_seconds=10)
        with pytest.raises(ValueError, match="not allowed"):
            runtime.start(argv=["not-allowlisted"], cwd=".", timeout_seconds=10)
        with pytest.raises(SandboxError):
            runtime.start(argv=["pytest", "../outside"], cwd=".", timeout_seconds=10)
        with pytest.raises(SandboxError):
            runtime.start(argv=[sys.executable, "-c", "print('no')"], cwd="..", timeout_seconds=10)
    finally:
        runtime.close()


def test_terminal_streams_incremental_unicode_accepts_input_and_exposes_stderr(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path, read_chunk_size=1)
    script = (
        "import sys; "
        "print('你好', flush=True); "
        "print('warn', file=sys.stderr, flush=True); "
        "line=sys.stdin.readline(); "
        "print('got:'+line.strip(), flush=True)"
    )
    try:
        started = runtime.start(
            argv=[sys.executable, "-c", script],
            cwd=".",
            timeout_seconds=10,
        )
        terminal_id = str(started["terminal_id"])
        _wait_for(runtime, terminal_id, text="你好")

        for invalid in (
            "",
            "nul\x00value",
            "two\nlines",
            "x" * (MAX_INPUT_BYTES + 1),
            "你" * (MAX_INPUT_BYTES // 3 + 1),
        ):
            with pytest.raises(ValueError, match="required|one line|exceeds"):
                runtime.write(terminal_id, invalid)
        assert runtime.write(terminal_id, "ping")["status"] == "running"
        final, events = _wait_for(runtime, terminal_id, status={"completed"}, text="got:ping")

        assert final["exit_code"] == 0
        stdout = "".join(str(event["text"]) for event in events if event["stream"] == "stdout")
        stderr = "".join(str(event["text"]) for event in events if event["stream"] == "stderr")
        assert "你好" in stdout
        assert "got:ping" in stdout
        assert "warn" in stderr
        assert "�" not in stdout
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("argv", "timeout_seconds", "message"),
    [
        ([], 10, "argv must contain"),
        ([sys.executable, "-c", ""], 10, "argv items"),
        ([sys.executable, "-c", "nul\x00value"], 10, "argv items"),
        ([sys.executable, *(["x"] * MAX_ARGV_ITEMS)], 10, "argv must contain"),
        ([sys.executable, "-c", "x" * (MAX_ARG_CHARS + 1)], 10, "argv items"),
        ([sys.executable, "-c", *(["x" * MAX_ARG_CHARS] * 4)], 10, "argv exceeds"),
        ([sys.executable, "-c", "print('no')"], True, "timeout_seconds"),
        ([sys.executable, "-c", "print('no')"], 0, "timeout_seconds"),
        ([sys.executable, "-c", "print('no')"], 3_601, "timeout_seconds"),
    ],
)
def test_terminal_validates_argv_and_timeout_before_start(
    tmp_path: Path,
    argv: list[str],
    timeout_seconds: object,
    message: str,
) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path)
    try:
        with pytest.raises(ValueError, match=message):
            runtime.start(argv=argv, cwd=".", timeout_seconds=timeout_seconds)
        assert runtime.snapshot()["status"] == "idle"
    finally:
        runtime.close()


def test_terminal_marks_nonzero_exit_and_rejects_stale_input(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path)
    try:
        started = runtime.start(
            argv=[sys.executable, "-c", "raise SystemExit(3)"],
            cwd=".",
            timeout_seconds=10,
        )
        terminal_id = str(started["terminal_id"])
        final, _events = _wait_for(runtime, terminal_id, status={"failed"})

        assert final["exit_code"] == 3
        with pytest.raises(ValueError, match="not running"):
            runtime.write(terminal_id, "late")
        with pytest.raises(ValueError, match="does not match"):
            runtime.write("terminal_000000000000", "stale")
    finally:
        runtime.close()


def test_terminal_stop_is_idempotent_and_close_stops_an_active_process(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path)
    started = runtime.start(
        argv=[sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(60)"],
        cwd=".",
        timeout_seconds=120,
    )
    terminal_id = str(started["terminal_id"])
    _wait_for(runtime, terminal_id, text="ready")

    first = runtime.stop(terminal_id)
    second = runtime.stop(terminal_id)

    assert first["status"] == "stopped"
    assert second["status"] == "stopped"

    replacement = runtime.start(
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=".",
        timeout_seconds=120,
    )
    runtime.close()
    closed = runtime.snapshot(terminal_id=str(replacement["terminal_id"]), after=0)
    assert closed["status"] == "stopped"


def test_terminal_stop_terminates_parent_and_child_processes(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path)
    pids: list[int] = []
    script = (
        "import os,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print(f'tree:{os.getpid()}:{child.pid}',flush=True);"
        "time.sleep(60)"
    )
    try:
        started = runtime.start(argv=[sys.executable, "-c", script], cwd=".", timeout_seconds=120)
        terminal_id = str(started["terminal_id"])
        _payload, events = _wait_for(runtime, terminal_id, text="tree:")
        stdout = "".join(str(event["text"]) for event in events if event["stream"] == "stdout")
        marker = next(line for line in stdout.splitlines() if line.startswith("tree:"))
        pids = [int(value) for value in marker.split(":")[1:]]
        assert all(_pid_exists(pid) for pid in pids)

        assert runtime.stop(terminal_id)["status"] == "stopped"
        for pid in pids:
            _wait_for_pid_exit(pid)
    finally:
        runtime.close()
        for pid in pids:
            if _pid_exists(pid):
                _terminate_pid(pid)


def test_terminal_times_out_and_releases_the_active_slot(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path)
    try:
        started = runtime.start(
            argv=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=".",
            timeout_seconds=1,
        )
        terminal_id = str(started["terminal_id"])
        with pytest.raises(ValueError, match="already running"):
            runtime.start(argv=[sys.executable, "-c", "print('second')"], cwd=".", timeout_seconds=10)

        final, _events = _wait_for(runtime, terminal_id, status={"timed_out"}, timeout=4.0)
        assert final["exit_code"] is not None

        replacement = runtime.start(
            argv=[sys.executable, "-c", "print('second')"],
            cwd=".",
            timeout_seconds=10,
        )
        _wait_for(runtime, str(replacement["terminal_id"]), status={"completed"})
    finally:
        runtime.close()


def test_terminal_cursor_reports_dropped_output(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    runtime = TerminalRuntime(tmp_path, max_output_chars=12, max_events=4, read_chunk_size=1)
    try:
        started = runtime.start(
            argv=[sys.executable, "-c", "print('abcdefghijklmnop', flush=True)"],
            cwd=".",
            timeout_seconds=10,
        )
        terminal_id = str(started["terminal_id"])
        _wait_for(runtime, terminal_id, status={"completed"})

        payload = runtime.snapshot(terminal_id=terminal_id, after=0)
        assert payload["truncated"] is True
        assert len(payload["events"]) <= 4
        assert int(payload["next"]) > 0
    finally:
        runtime.close()


@contextmanager
def _running_terminal_workbench(workspace: Path):
    runtime = TerminalRuntime(workspace)
    handler = server.create_workbench_handler(workspace, terminal_runtime=runtime)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield str(host), int(port)
    finally:
        runtime.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2.0)


def _request(host: str, port: int, method: str, path: str, body: dict[str, object] | None = None):
    connection = HTTPConnection(host, port, timeout=3.0)
    try:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        headers = {} if body is None else {"Content-Type": "application/json"}
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_terminal_http_start_poll_input_and_stop(tmp_path: Path) -> None:
    _enable_terminal(tmp_path)
    script = "import sys,time; print('ready',flush=True); print(sys.stdin.readline().strip(),flush=True); time.sleep(60)"
    with _running_terminal_workbench(tmp_path) as (host, port):
        status, started = _request(
            host,
            port,
            "POST",
            "/api/terminal/start",
            {"argv": [sys.executable, "-c", script], "cwd": ".", "timeout_seconds": 120},
        )
        assert status == 200
        terminal_id = str(started["terminal_id"])

        status, output = _request(
            host,
            port,
            "GET",
            f"/api/terminal?terminal_id={terminal_id}&after={started['next']}&timeout=1",
        )
        assert status == 200
        assert "ready" in "".join(event["text"] for event in output["events"])

        status, payload = _request(
            host,
            port,
            "POST",
            "/api/terminal/input",
            {"terminal_id": terminal_id, "data": "hello"},
        )
        assert status == 200
        assert payload["status"] == "running"

        status, stopped = _request(
            host,
            port,
            "POST",
            "/api/terminal/stop",
            {"terminal_id": terminal_id},
        )
        assert status == 200
        assert stopped["status"] == "stopped"
