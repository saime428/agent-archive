from __future__ import annotations

import codecs
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from agent.config import load_config
from agent.policy.sandbox import WorkspaceSandbox
from agent.tools.shell import (
    command_policy_denial,
    process_group_kwargs,
    stop_process_tree,
    validate_command_paths,
)


DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 3_600
MAX_POLL_SECONDS = 15.0
MAX_ARGV_ITEMS = 64
MAX_ARG_CHARS = 8_192
MAX_ARGV_CHARS = 32_768
MAX_INPUT_BYTES = 16_384
MAX_OUTPUT_CHARS = 1_048_576
MAX_OUTPUT_EVENTS = 4_096
READ_CHUNK_SIZE = 4_096
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped", "timed_out"})


@dataclass
class _TerminalState:
    terminal_id: str
    argv: tuple[str, ...]
    cwd_display: str
    timeout_seconds: int
    process: subprocess.Popen[bytes]
    status: str = "running"
    exit_code: int | None = None
    cleanup_error: str | None = None
    events: deque[dict[str, Any]] = field(default_factory=deque)
    output_chars: int = 0
    next_sequence: int = 0
    condition: threading.Condition = field(default_factory=threading.Condition)
    finalize_lock: threading.Lock = field(default_factory=threading.Lock)
    readers: tuple[threading.Thread, ...] = ()


class TerminalRuntime:
    def __init__(
        self,
        workspace: Path,
        *,
        max_output_chars: int = MAX_OUTPUT_CHARS,
        max_events: int = MAX_OUTPUT_EVENTS,
        read_chunk_size: int = READ_CHUNK_SIZE,
    ) -> None:
        self._workspace = workspace.resolve()
        self._max_output_chars = max_output_chars
        self._max_events = max_events
        self._read_chunk_size = read_chunk_size
        self._state: _TerminalState | None = None
        self._state_lock = threading.Lock()
        self._closed = False

    def start(
        self,
        *,
        argv: object,
        cwd: object = ".",
        timeout_seconds: object = None,
    ) -> dict[str, Any]:
        config, _diagnostics = load_config(self._workspace)
        if not config.terminal_enabled:
            raise ValueError(
                "Terminal is disabled. Run `agent config set terminal_enabled true --cwd <workspace>` first."
            )
        command = _validated_argv(argv)
        timeout = _validated_timeout(timeout_seconds)
        resolved_cwd, cwd_display = _validated_cwd(self._workspace, cwd)
        sandbox = WorkspaceSandbox(self._workspace)
        denial = command_policy_denial(command, config.allowed_commands)
        if denial is not None:
            raise ValueError(denial)
        validate_command_paths(command, sandbox)

        with self._state_lock:
            if self._closed:
                raise ValueError("Terminal runtime is closed.")
            if self._state is not None and self._state.status == "running":
                raise ValueError("A terminal process is already running.")
            process = subprocess.Popen(
                command,
                cwd=resolved_cwd,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **process_group_kwargs(),
            )
            state = _TerminalState(
                terminal_id=f"terminal_{uuid.uuid4().hex[:12]}",
                argv=tuple(command),
                cwd_display=cwd_display,
                timeout_seconds=timeout,
                process=process,
            )
            self._state = state

        self._append_event(state, "system", "Process started.\n")
        assert process.stdout is not None and process.stderr is not None
        readers = (
            threading.Thread(target=self._read_stream, args=(state, "stdout", process.stdout), daemon=True),
            threading.Thread(target=self._read_stream, args=(state, "stderr", process.stderr), daemon=True),
        )
        state.readers = readers
        for reader in readers:
            reader.start()
        threading.Thread(target=self._monitor, args=(state,), daemon=True).start()
        return self.snapshot(terminal_id=state.terminal_id, after=0)

    def snapshot(
        self,
        *,
        terminal_id: str | None = None,
        after: int = 0,
        timeout: float = 0.0,
    ) -> dict[str, Any]:
        if type(after) is not int or after < 0:
            raise ValueError("after must be a non-negative integer.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= MAX_POLL_SECONDS:
            raise ValueError(f"timeout must be between 0 and {int(MAX_POLL_SECONDS)} seconds.")
        config, _diagnostics = load_config(self._workspace)
        state = self._state
        if state is None:
            if terminal_id:
                raise ValueError("Terminal id does not match the current process.")
            return _idle_payload(config.terminal_enabled)
        _require_terminal_id(state, terminal_id)
        deadline = time.monotonic() + float(timeout)
        with state.condition:
            if after > state.next_sequence:
                raise ValueError("after is beyond the current terminal cursor.")
            while after == state.next_sequence and state.status == "running":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                state.condition.wait(remaining)
            return self._payload_locked(state, enabled=config.terminal_enabled, after=after)

    def write(self, terminal_id: str, data: object) -> dict[str, Any]:
        state = self._require_state(terminal_id)
        if not isinstance(data, str) or not data:
            raise ValueError("Terminal input is required.")
        if len(data.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"Terminal input exceeds {MAX_INPUT_BYTES} UTF-8 bytes.")
        if "\x00" in data or "\n" in data or "\r" in data:
            raise ValueError("Terminal input must be one line without NUL characters.")
        with state.condition:
            if state.status != "running":
                raise ValueError("Terminal process is not running.")
            stream = state.process.stdin
        if stream is None or stream.closed:
            raise ValueError("Terminal stdin is closed.")
        try:
            stream.write((data + "\n").encode("utf-8"))
            stream.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise ValueError("Terminal stdin is closed.") from exc
        return self.snapshot(terminal_id=terminal_id, after=state.next_sequence)

    def stop(self, terminal_id: str) -> dict[str, Any]:
        state = self._require_state(terminal_id)
        self._finalize(state, "stopped", stop_tree=True)
        return self.snapshot(terminal_id=terminal_id, after=0)

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            state = self._state
        if state is not None and state.status == "running":
            self._finalize(state, "stopped", stop_tree=True)

    def _require_state(self, terminal_id: str) -> _TerminalState:
        state = self._state
        if state is None:
            raise ValueError("Terminal id does not match the current process.")
        _require_terminal_id(state, terminal_id)
        return state

    def _read_stream(self, state: _TerminalState, name: str, stream: BinaryIO) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                raw = stream.read(self._read_chunk_size)
                if not raw:
                    break
                text = decoder.decode(raw)
                if text:
                    self._append_event(state, name, text)
            tail = decoder.decode(b"", final=True)
            if tail:
                self._append_event(state, name, tail)
        finally:
            stream.close()

    def _monitor(self, state: _TerminalState) -> None:
        try:
            state.process.wait(timeout=state.timeout_seconds)
        except subprocess.TimeoutExpired:
            self._finalize(state, "timed_out", stop_tree=True)
            return
        self._finalize(state, "completed" if state.process.returncode == 0 else "failed", stop_tree=False)

    def _finalize(self, state: _TerminalState, status: str, *, stop_tree: bool) -> None:
        with state.finalize_lock:
            with state.condition:
                if state.status in _TERMINAL_STATUSES:
                    return
            cleanup_error = stop_process_tree(state.process) if stop_tree and state.process.poll() is None else None
            if state.process.stdin is not None and not state.process.stdin.closed:
                state.process.stdin.close()
            for reader in state.readers:
                if reader is not threading.current_thread():
                    reader.join(timeout=1.0)
            with state.condition:
                state.exit_code = state.process.poll()
                state.cleanup_error = cleanup_error
                state.status = status
                self._append_event(state, "system", _terminal_message(status, state.exit_code, cleanup_error))
                state.condition.notify_all()

    def _append_event(self, state: _TerminalState, stream: str, text: str) -> None:
        if not text:
            return
        with state.condition:
            event = {"sequence": state.next_sequence, "stream": stream, "text": text}
            state.next_sequence += 1
            state.events.append(event)
            state.output_chars += len(text)
            while state.events and (
                state.output_chars > self._max_output_chars or len(state.events) > self._max_events
            ):
                removed = state.events.popleft()
                state.output_chars -= len(str(removed["text"]))
            state.condition.notify_all()

    @staticmethod
    def _payload_locked(state: _TerminalState, *, enabled: bool, after: int) -> dict[str, Any]:
        earliest = int(state.events[0]["sequence"]) if state.events else state.next_sequence
        truncated = after < earliest
        cursor = max(after, earliest)
        return {
            "enabled": enabled,
            "terminal_id": state.terminal_id,
            "status": state.status,
            "argv": list(state.argv),
            "cwd": state.cwd_display,
            "timeout_seconds": state.timeout_seconds,
            "exit_code": state.exit_code,
            "events": [dict(event) for event in state.events if int(event["sequence"]) >= cursor],
            "next": state.next_sequence,
            "truncated": truncated,
            "cleanup_error": state.cleanup_error,
        }


def _validated_argv(raw: object) -> list[str]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ARGV_ITEMS:
        raise ValueError(f"argv must contain between 1 and {MAX_ARGV_ITEMS} strings.")
    if any(not isinstance(item, str) or not item or len(item) > MAX_ARG_CHARS or "\x00" in item for item in raw):
        raise ValueError(f"argv items must be non-empty strings up to {MAX_ARG_CHARS} characters without NUL.")
    if sum(len(item) for item in raw) > MAX_ARGV_CHARS:
        raise ValueError(f"argv exceeds {MAX_ARGV_CHARS} total characters.")
    return list(raw)


def _validated_timeout(raw: object) -> int:
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    if type(raw) is not int or not 1 <= raw <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}.")
    return raw


def _validated_cwd(workspace: Path, raw: object) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("cwd must be a non-empty relative path.")
    requested = Path(raw)
    if requested.is_absolute() or raw.startswith(("~", "~/", "~\\")):
        raise ValueError("cwd must be relative to the workspace.")
    resolved = WorkspaceSandbox(workspace).resolve_read_path(raw, allow_external=False)
    if not resolved.is_dir():
        raise ValueError(f"Terminal cwd is not a directory: {raw}")
    relative = resolved.relative_to(workspace)
    return resolved, relative.as_posix() or "."


def _require_terminal_id(state: _TerminalState, terminal_id: str | None) -> None:
    if terminal_id is not None and terminal_id != state.terminal_id:
        raise ValueError("Terminal id does not match the current process.")


def _idle_payload(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "terminal_id": None,
        "status": "idle",
        "argv": [],
        "cwd": ".",
        "timeout_seconds": None,
        "exit_code": None,
        "events": [],
        "next": 0,
        "truncated": False,
        "cleanup_error": None,
    }


def _terminal_message(status: str, exit_code: int | None, cleanup_error: str | None) -> str:
    if cleanup_error:
        return f"Process {status}; cleanup failed: {cleanup_error}\n"
    if status == "timed_out":
        return "Process timed out and was stopped.\n"
    if status == "stopped":
        return "Process stopped.\n"
    return f"Process exited with code {exit_code}.\n"
