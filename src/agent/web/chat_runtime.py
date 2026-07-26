from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from agent import _user_store
from agent.config import load_config
from agent.core.chat import ChatSession, ConversationState
from agent.core.context import RunContext
from agent.core.redaction import redact_record, redact_value
from agent.core.run_control import RunControl, validate_timeout_seconds
from agent.core.run_lease import RunLeaseBusy, RunLeaseError, WorkspaceRunLease
from agent.llm.factory import make_llm
from agent.secrets import load_workspace_secrets
from agent.web import chats


CHAT_JOB_TTL_SECONDS = 300.0
APPROVAL_WAIT_TIMEOUT_SECONDS = CHAT_JOB_TTL_SECONDS
STREAM_EVENT_BATCH_CHARS = 64
_APPROVAL_POLL_SECONDS = 0.1
_JOB_VERSION = 1
_JOB_ID_PATTERN = re.compile(r"job_[0-9a-f]{12}\Z", re.ASCII)
_RUN_ID_PATTERN = re.compile(r"run_[0-9]{8}_[0-9]{6}_[0-9]{6}\Z", re.ASCII)
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "timed_out", "interrupted", "failed"})
_RESUMABLE_STATUSES = frozenset({"cancelled", "timed_out", "interrupted", "failed"})
_TERMINAL_EVENTS = {
    "final": "completed",
    "cancelled": "cancelled",
    "timed_out": "timed_out",
    "interrupted": "interrupted",
    "failed": "failed",
}
_JOB_FIELDS = frozenset(
    {
        "version",
        "job_id",
        "session_id",
        "run_id",
        "status",
        "started_at",
        "completed_at",
        "timeout_seconds",
        "resumed_from_job_id",
        "message",
    }
)
_MAX_METADATA_BYTES = 128_000
_MAX_EVENT_BYTES = 1_000_000
_MAX_EVENTS_BYTES = 64_000_000


class ChatJobStoreError(OSError):
    pass


ApprovalDecision = bool | Literal["timed_out", "cancelled", "run_timed_out"]


@dataclass
class _ChatJob:
    job_id: str
    session_id: str
    run_id: str
    message: str
    timeout_seconds: int
    resumed_from_job_id: str | None
    started_at: float
    started_at_utc: str
    control: RunControl
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    approval_pending: bool = False
    approval_deadline: float | None = None
    approval_decision: ApprovalDecision | None = None
    done: bool = False
    completed_at: float | None = None
    lease: WorkspaceRunLease | None = None


class ChatRuntime:
    def __init__(
        self,
        workspace: Path,
        *,
        llm_factory: Callable[[Any], Any] = make_llm,
        mcp_runtime: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        approval_timeout: float = APPROVAL_WAIT_TIMEOUT_SECONDS,
        job_ttl: float = CHAT_JOB_TTL_SECONDS,
    ) -> None:
        self._workspace = workspace.resolve()
        self._llm_factory = llm_factory
        self._mcp_runtime = mcp_runtime
        self._clock = clock
        self._approval_timeout = approval_timeout
        self._job_ttl = job_ttl
        self._jobs: dict[str, _ChatJob] = {}
        self._active_sessions: set[str] = set()
        self._jobs_lock = threading.Lock()
        self._recover_interrupted_job()

    def start(
        self,
        *,
        message: str,
        session_id: str | None,
        timeout_seconds: object = None,
    ) -> dict[str, Any]:
        return self._start(
            message=message,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            resumed_from_job_id=None,
        )

    def poll(self, job_id: str, *, after: int = 0, timeout: float = 0.0) -> dict[str, Any]:
        self._prune()
        if type(after) is not int or after < 0:
            raise ValueError("after must be non-negative.")
        job = self._get_job(job_id)
        deadline = self._clock() + max(timeout, 0.0)
        with job.condition:
            while len(job.events) <= after and not job.done:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                job.condition.wait(remaining)
            events = [dict(event) for event in job.events[after:]]
            return {
                "job_id": job.job_id,
                "events": events,
                "done": job.done,
                "next": after + len(events),
                "status": job.status,
            }

    def decide(self, *, job_id: str, approve: bool) -> dict[str, Any]:
        self._prune()
        job = self._get_job(job_id)
        with job.condition:
            if job.approval_decision == "timed_out":
                raise ValueError("chat approval has expired.")
            if job.done or job.status in _TERMINAL_STATUSES:
                raise ValueError("chat job is already finished.")
            if not job.approval_pending:
                raise ValueError("chat job has no pending approval.")
            if job.approval_deadline is None or job.approval_deadline <= self._clock():
                job.approval_pending = False
                job.approval_deadline = None
                job.approval_decision = "timed_out"
                job.condition.notify_all()
                raise ValueError("chat approval has expired.")
            job.approval_pending = False
            job.approval_deadline = None
            job.approval_decision = approve
            job.condition.notify_all()
        return {"status": "ok", "job_id": job.job_id, "approved": approve}

    def cancel(self, job_id: str) -> dict[str, Any]:
        self._prune()
        job = self._get_job(job_id)
        with job.condition:
            if job.done or job.status in _TERMINAL_STATUSES:
                return {"status": job.status, "job_id": job.job_id}
            if job.status == "running":
                job.status = "cancel_requested"
                self._write_metadata(job)
            job.control.request_cancel()
            job.approval_decision = "cancelled"
            job.condition.notify_all()
            return {"status": job.status, "job_id": job.job_id}

    def resume(
        self,
        *,
        job_id: str,
        message: str,
        timeout_seconds: object = None,
    ) -> dict[str, Any]:
        previous = self._get_job(job_id)
        if previous.status not in _RESUMABLE_STATUSES:
            raise ValueError(f"Chat job {job_id} cannot be resumed from status {previous.status}.")
        return self._start(
            message=message,
            session_id=previous.session_id,
            timeout_seconds=timeout_seconds,
            resumed_from_job_id=previous.job_id,
        )

    def _start(
        self,
        *,
        message: str,
        session_id: str | None,
        timeout_seconds: object,
        resumed_from_job_id: str | None,
    ) -> dict[str, Any]:
        self._prune()
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message is required.")
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("session_id must be a string.")
        timeout = validate_timeout_seconds(timeout_seconds)
        message = message.strip()
        load_workspace_secrets(self._workspace)
        config, diagnostics = load_config(self._workspace)
        claimed_session_id: str | None = None
        lease: WorkspaceRunLease | None = None
        job: _ChatJob | None = None
        persisted = False
        try:
            if session_id:
                self._claim_session(session_id)
                claimed_session_id = session_id
            state = chats.load_or_create_chat_state(self._workspace, session_id)
            if claimed_session_id is None:
                self._claim_session(state.session_id)
                claimed_session_id = state.session_id
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            run_id = RunContext.create(message, cwd=self._workspace).run_id
            lease = WorkspaceRunLease.acquire(
                self._workspace,
                owner={"kind": "web", "session_id": state.session_id, "job_id": job_id, "run_id": run_id},
            )
            session_path = state.cwd / ".agent" / "chats" / state.session_id / "session.json"
            if not session_path.is_file():
                state.save(config)
            job = _ChatJob(
                job_id=job_id,
                session_id=state.session_id,
                run_id=run_id,
                message=message,
                timeout_seconds=timeout,
                resumed_from_job_id=resumed_from_job_id,
                started_at=self._clock(),
                started_at_utc=_utc_now(),
                control=RunControl.with_timeout(timeout),
                lease=lease,
            )
            persisted = True
            self._create_job(job)
            with self._jobs_lock:
                self._jobs[job.job_id] = job
            self._append_event(job, {"event": "chat_started", "session_id": state.session_id, "run_id": run_id})
            thread = threading.Thread(
                target=self._run_job,
                args=(job, state, config, diagnostics),
                daemon=True,
                name=f"chat-job-{job.job_id}",
            )
            thread.start()
        except BaseException:
            if job is not None:
                with self._jobs_lock:
                    if self._jobs.get(job.job_id) is job:
                        del self._jobs[job.job_id]
                if persisted:
                    self._rollback_job(job.job_id)
            if lease is not None:
                lease.release()
            if claimed_session_id is not None:
                self._release_session(claimed_session_id)
            raise
        assert job is not None
        return {
            "status": "running",
            "job_id": job.job_id,
            "session_id": job.session_id,
            "run_id": job.run_id,
        }

    @contextmanager
    def _reserve_session(self, session_id: object) -> Iterator[None]:
        if not isinstance(session_id, str) or not session_id:
            yield
            return
        self._claim_session(session_id)
        try:
            yield
        finally:
            self._release_session(session_id)

    @contextmanager
    def _reserve_turn(self, session_id: object) -> Iterator[None]:
        with self._reserve_session(session_id):
            owner = {"kind": "web-sync"}
            if isinstance(session_id, str) and session_id:
                owner["session_id"] = session_id
            with WorkspaceRunLease.acquire(self._workspace, owner=owner):
                yield

    def _claim_session(self, session_id: str) -> None:
        with self._jobs_lock:
            if session_id in self._active_sessions:
                raise ValueError(f"Chat session {session_id} already has an active turn.")
            self._active_sessions.add(session_id)
        try:
            job_id = self._read_active()
            if job_id is not None:
                record = self._read_metadata(job_id)
                if record["status"] in {"running", "cancel_requested"} and record["session_id"] == session_id:
                    raise ValueError(f"Chat session {session_id} already has an active turn.")
        except BaseException:
            self._release_session(session_id)
            raise

    def _release_session(self, session_id: str) -> None:
        with self._jobs_lock:
            self._active_sessions.discard(session_id)

    def _prune(self) -> None:
        now = self._clock()
        with self._jobs_lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.done and job.completed_at is not None and now - job.completed_at > self._job_ttl
            ]
            for job_id in expired:
                del self._jobs[job_id]

    def _get_job(self, job_id: str) -> _ChatJob:
        _validate_job_id(job_id)
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        record = self._read_metadata(job_id)
        events = self._read_events(job_id)
        loaded = self._job_from_record(record, events)
        with self._jobs_lock:
            return self._jobs.setdefault(job_id, loaded)

    def _append_event(self, job: _ChatJob, event: dict[str, Any]) -> None:
        with job.condition:
            now = self._clock()
            safe = redact_record(event).value
            record = dict(safe)
            record["sequence"] = len(job.events)
            record["elapsed_ms"] = max(0, int((now - job.started_at) * 1000))
            record = self._append_event_file(job.job_id, record)
            if record.get("event") == "approval_required":
                job.approval_decision = None
                job.approval_pending = True
                job.approval_deadline = now + self._approval_timeout
            job.events.append(record)
            job.condition.notify_all()

    def _run_job(self, job: _ChatJob, state: ConversationState, config: Any, diagnostics: Any) -> None:
        pending_stream_event: dict[str, Any] | None = None

        def flush_stream_event() -> None:
            nonlocal pending_stream_event
            if pending_stream_event is not None:
                self._append_event(job, pending_stream_event)
                pending_stream_event = None

        def handle_event(event: dict[str, Any]) -> None:
            nonlocal pending_stream_event
            name = event.get("event")
            if name in {"run_cancelled", "run_timed_out"}:
                flush_stream_event()
                return
            if name == "model_stream_chunk":
                kind = str(event.get("kind") or "content")
                text = str(event.get("text") or "")
                if pending_stream_event is not None and pending_stream_event["kind"] != kind:
                    flush_stream_event()
                if not text:
                    return
                if pending_stream_event is None:
                    pending_stream_event = {**event, "kind": kind, "text": ""}
                pending_stream_event["text"] += text
                pending_stream_event["chunk_chars"] = len(pending_stream_event["text"])
                # ponytail: size batching removes per-token SSE churn; add timed flushing only if latency is measured.
                if len(pending_stream_event["text"]) >= STREAM_EVENT_BATCH_CHARS:
                    flush_stream_event()
                return
            flush_stream_event()
            self._append_event(job, event)

        def handle_approval(_action: Any) -> ApprovalDecision:
            with job.condition:
                while job.approval_decision is None and job.approval_pending and not job.done:
                    stop_reason = job.control.stop_reason()
                    if stop_reason == "cancelled":
                        return "cancelled"
                    if stop_reason == "timed_out":
                        return "run_timed_out"
                    deadline = job.approval_deadline
                    remaining = (deadline - self._clock()) if deadline is not None else 0.0
                    if remaining <= 0:
                        job.approval_decision = "timed_out"
                        job.approval_pending = False
                        job.approval_deadline = None
                        return "timed_out"
                    job.condition.wait(min(remaining, _APPROVAL_POLL_SECONDS))
                decision = job.approval_decision
                job.approval_decision = None
                job.approval_pending = False
                job.approval_deadline = None
                if decision in {"cancelled", "run_timed_out"}:
                    return decision
                return "timed_out" if decision in {None, "timed_out"} else decision

        try:
            session = ChatSession(
                cwd=self._workspace,
                llm=self._llm_factory(config),
                config=config,
                state=state,
                mcp_runtime=self._mcp_runtime,
            )
            result = session.run_turn(
                job.message,
                approval_handler=handle_approval,
                event_handler=handle_event,
                stream_handler=lambda _text: None,
                run_id=job.run_id,
                job_id=job.job_id,
                resumed_from_job_id=job.resumed_from_job_id,
                control=job.control,
            )
            payload = chats.build_chat_turn_response(self._workspace, session, result, diagnostics)
            terminal_reason = str(payload.get("terminal_reason") or "")
            if terminal_reason == "cancelled":
                self._finish_job(job, "cancelled", {"event": "cancelled", **payload})
            elif terminal_reason == "timed_out":
                self._finish_job(job, "timed_out", {"event": "timed_out", **payload})
            else:
                self._finish_job(job, "completed", {"event": "final", **payload})
        except Exception as exc:  # worker failures are durable and visible through SSE
            if job.status not in _TERMINAL_STATUSES:
                try:
                    error = str(redact_value(str(exc)).value)
                    self._record_abnormal_turn(
                        job,
                        state,
                        config,
                        terminal_reason="failed",
                        summary=f"Worker failed: {error}",
                    )
                    self._append_event(job, {"event": "error", "error": error, "run_id": job.run_id})
                    self._finish_job(job, "failed", {"event": "failed", "error": error, "run_id": job.run_id})
                except Exception:
                    job.status = "failed"
        finally:
            if job.lease is not None:
                job.lease.release()
                job.lease = None
            self._release_session(job.session_id)
            self._mark_done_in_memory(job, job.status)

    def _finish_job(self, job: _ChatJob, status: str, event: dict[str, Any]) -> None:
        with job.condition:
            if job.done or job.status in _TERMINAL_STATUSES:
                return
            self._append_event(job, event)
            job.status = status
            self._write_metadata(job, completed_at=_utc_now())
            self._clear_active(job.job_id)

    def _mark_done_in_memory(self, job: _ChatJob, status: str) -> None:
        with job.condition:
            job.status = status
            job.approval_pending = False
            job.approval_deadline = None
            job.done = True
            job.completed_at = self._clock()
            job.condition.notify_all()

    def _create_job(self, job: _ChatJob) -> None:
        root = self._store_root(create=True)
        metadata_path = _metadata_path(root, job.job_id)
        events_path = _events_path(root, job.job_id)
        if _user_store.lexists(metadata_path) or _user_store.lexists(events_path):
            raise ChatJobStoreError(f"Chat job already exists: {job.job_id}")
        self._write_metadata(job)
        try:
            with events_path.open("xb") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            _user_store.require_plain_file(events_path, message="Chat job events must be a regular file.")
            _user_store.sync_directory(root)
            self._write_active(job.job_id)
        except (_user_store.UserStoreError, OSError) as exc:
            raise ChatJobStoreError("Could not create durable chat job state.") from exc

    def _write_metadata(self, job: _ChatJob, *, completed_at: str | None = None) -> None:
        record = {
            "version": _JOB_VERSION,
            "job_id": job.job_id,
            "session_id": job.session_id,
            "run_id": job.run_id,
            "status": job.status,
            "started_at": job.started_at_utc,
            "completed_at": completed_at,
            "timeout_seconds": job.timeout_seconds,
            "resumed_from_job_id": job.resumed_from_job_id,
            "message": str(redact_value(job.message).value),
        }
        root = self._store_root(create=True)
        try:
            _user_store.atomic_replace_json(root, _metadata_path(root, job.job_id), record, max_bytes=_MAX_METADATA_BYTES)
        except _user_store.UserStoreError as exc:
            raise ChatJobStoreError("Could not write chat job metadata.") from exc

    def _read_metadata(self, job_id: str) -> dict[str, Any]:
        root = self._store_root(create=False)
        if root is None:
            raise ValueError(f"Unknown chat job: {job_id}")
        path = _metadata_path(root, job_id)
        if not _user_store.lexists(path):
            raise ValueError(f"Unknown chat job: {job_id}")
        try:
            _user_store.require_plain_file(path, message="Chat job metadata must be a regular file.")
            if path.stat().st_size > _MAX_METADATA_BYTES:
                raise ValueError("Chat job metadata is too large.")
            record = json.loads(path.read_text(encoding="utf-8"))
        except _user_store.UserStoreError as exc:
            raise ValueError(exc.message) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Chat job metadata is invalid.") from exc
        _validate_metadata(record, job_id)
        return record

    def _read_events(self, job_id: str) -> list[dict[str, Any]]:
        root = self._store_root(create=False)
        if root is None:
            raise ValueError(f"Unknown chat job: {job_id}")
        path = _events_path(root, job_id)
        try:
            _user_store.require_plain_file(path, message="Chat job events must be a regular file.")
            if path.stat().st_size > _MAX_EVENTS_BYTES:
                raise ValueError("Chat job event log is too large.")
            raw = path.read_bytes()
        except _user_store.UserStoreError as exc:
            raise ValueError(exc.message) from exc
        except OSError as exc:
            raise ValueError("Chat job event log could not be read.") from exc
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b"\n"):
            lines.pop()
        events: list[dict[str, Any]] = []
        for sequence, line in enumerate(lines):
            if len(line) > _MAX_EVENT_BYTES:
                raise ValueError("Chat job event is too large.")
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("Chat job event log contains an invalid complete record.") from exc
            if (
                not isinstance(event, dict)
                or event.get("sequence") != sequence
                or not isinstance(event.get("event"), str)
            ):
                raise ValueError("Chat job event sequence is invalid.")
            events.append(event)
        return events

    def _append_event_file(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        root = self._store_root(create=False)
        if root is None:
            raise ChatJobStoreError("Chat job storage is missing.")
        path = _events_path(root, job_id)
        try:
            _user_store.require_plain_file(path, message="Chat job events must be a regular file.")
            encoded = (json.dumps(event, ensure_ascii=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")
            if len(encoded) > _MAX_EVENT_BYTES:
                raise ChatJobStoreError("Chat job event is too large.")
            record = json.loads(encoded)
            with path.open("r+b", buffering=0) as handle:
                size = handle.seek(0, os.SEEK_END)
                if size > _MAX_EVENTS_BYTES:
                    raise ChatJobStoreError("Chat job event log is too large.")
                if size:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        handle.seek(0)
                        tail = handle.read()
                        handle.truncate(tail.rfind(b"\n") + 1)
                handle.seek(0, os.SEEK_END)
                handle.write(encoded)
                os.fsync(handle.fileno())
            return record
        except _user_store.UserStoreError as exc:
            raise ChatJobStoreError("Could not append chat job event.") from exc
        except OSError as exc:
            raise ChatJobStoreError("Could not append chat job event.") from exc

    def _write_active(self, job_id: str) -> None:
        root = self._store_root(create=True)
        try:
            _user_store.atomic_replace_json(
                root,
                root / "active.json",
                {"version": _JOB_VERSION, "job_id": job_id},
                max_bytes=256,
            )
        except _user_store.UserStoreError as exc:
            raise ChatJobStoreError("Could not write the active chat job pointer.") from exc

    def _read_active(self) -> str | None:
        root = self._store_root(create=False)
        if root is None:
            return None
        path = root / "active.json"
        if not _user_store.lexists(path):
            return None
        try:
            _user_store.require_plain_file(path, message="Active chat job pointer must be a regular file.")
            value = json.loads(path.read_text(encoding="utf-8"))
        except _user_store.UserStoreError as exc:
            raise ValueError(exc.message) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Active chat job pointer is invalid.") from exc
        if not isinstance(value, dict) or set(value) != {"version", "job_id"} or value.get("version") != 1:
            raise ValueError("Active chat job pointer is invalid.")
        _validate_job_id(value.get("job_id"))
        return value["job_id"]

    def _clear_active(self, job_id: str) -> None:
        root = self._store_root(create=False)
        if root is None:
            return
        path = root / "active.json"
        if not _user_store.lexists(path) or self._read_active() != job_id:
            return
        try:
            _user_store.require_plain_file(path, message="Active chat job pointer must be a regular file.")
            path.unlink()
            _user_store.sync_directory(root)
        except (_user_store.UserStoreError, OSError) as exc:
            raise ChatJobStoreError("Could not clear the active chat job pointer.") from exc

    def _rollback_job(self, job_id: str) -> None:
        root = self._store_root(create=False)
        if root is None:
            return
        try:
            self._clear_active(job_id)
        except (ValueError, ChatJobStoreError):
            pass
        for path in (_events_path(root, job_id), _metadata_path(root, job_id)):
            if not _user_store.lexists(path):
                continue
            try:
                _user_store.require_plain_file(path, message="Chat job rollback target must be a regular file.")
                path.unlink()
            except (_user_store.UserStoreError, OSError):
                continue
        try:
            _user_store.sync_directory(root)
        except _user_store.UserStoreError:
            pass

    def _store_root(self, *, create: bool) -> Path | None:
        agent_root = self._workspace / ".agent"
        root = agent_root / "chat-jobs"
        try:
            if not _user_store.lexists(agent_root):
                if not create:
                    return None
                _user_store.make_directory(agent_root, parent=self._workspace, message="Could not create Agent storage.")
            else:
                _user_store.require_real_directory(agent_root, message="Agent storage must be a real directory.")
            if not _user_store.lexists(root):
                if not create:
                    return None
                _user_store.make_directory(root, parent=agent_root, message="Could not create chat job storage.")
            else:
                _user_store.require_real_directory(root, message="Chat job storage must be a real directory.")
            return root
        except _user_store.UserStoreError as exc:
            raise ChatJobStoreError(exc.message) from exc

    def _job_from_record(self, record: dict[str, Any], events: list[dict[str, Any]]) -> _ChatJob:
        status = record["status"]
        terminal_status = _last_terminal_status(events)
        if terminal_status is not None:
            if status in _TERMINAL_STATUSES and status != terminal_status:
                raise ValueError("Chat job metadata conflicts with its terminal event.")
            status = terminal_status
        job = _ChatJob(
            job_id=record["job_id"],
            session_id=record["session_id"],
            run_id=record["run_id"],
            message=record["message"],
            timeout_seconds=record["timeout_seconds"],
            resumed_from_job_id=record["resumed_from_job_id"],
            started_at=self._clock(),
            started_at_utc=record["started_at"],
            control=RunControl(),
            status=status,
            events=events,
            done=status in _TERMINAL_STATUSES,
            completed_at=self._clock() if status in _TERMINAL_STATUSES else None,
        )
        pending = False
        for event in events:
            if event["event"] == "approval_required":
                pending = True
            elif event["event"] in {"approval_granted", "approval_denied", "approval_timed_out", *_TERMINAL_EVENTS}:
                pending = False
        if pending:
            job.approval_pending = True
            job.approval_deadline = self._clock() + self._approval_timeout
        return job

    def _recover_interrupted_job(self) -> None:
        try:
            lease = WorkspaceRunLease.acquire(self._workspace, owner={"kind": "recovery"})
        except RunLeaseBusy:
            return
        except RunLeaseError as exc:
            raise ChatJobStoreError(str(exc)) from exc
        with lease:
            job_id = self._read_active()
            if job_id is None:
                return
            record = self._read_metadata(job_id)
            events = self._read_events(job_id)
            job = self._job_from_record(record, events)
            if job.status in _TERMINAL_STATUSES:
                if record["status"] != job.status:
                    self._write_metadata(job, completed_at=_utc_now())
                self._clear_active(job_id)
                return
            if record["status"] not in {"running", "cancel_requested"}:
                raise ValueError(f"Active chat job has invalid status: {record['status']}")
            config, _diagnostics = load_config(self._workspace)
            state = ConversationState.load(self._workspace, job.session_id)
            self._record_abnormal_turn(
                job,
                state,
                config,
                terminal_reason="interrupted",
                summary="Run interrupted by service restart.",
            )
            self._append_event(job, {"event": "interrupted", "run_id": job.run_id, "session_id": job.session_id})
            job.status = "interrupted"
            self._write_metadata(job, completed_at=_utc_now())
            self._clear_active(job.job_id)

    def _record_abnormal_turn(
        self,
        job: _ChatJob,
        state: ConversationState,
        config: Any,
        *,
        terminal_reason: str,
        summary: str,
    ) -> None:
        if not any(turn.job_id == job.job_id for turn in state.turns):
            state.add_turn(
                user=job.message,
                run_id=job.run_id,
                status="error",
                completed=False,
                terminal_reason=terminal_reason,
                final="",
                last_action="runtime",
                last_observation_summary=summary,
                job_id=job.job_id,
                resumed_from_job_id=job.resumed_from_job_id,
            )
            state.save(config)
        self._write_minimal_summary(job, terminal_reason=terminal_reason, summary=summary)

    def _write_minimal_summary(self, job: _ChatJob, *, terminal_reason: str, summary: str) -> None:
        if _RUN_ID_PATTERN.fullmatch(job.run_id) is None:
            raise ValueError("Chat job run id is invalid.")
        agent_root = self._workspace / ".agent"
        runs_root = agent_root / "runs"
        run_root = runs_root / job.run_id
        try:
            for path, parent in ((runs_root, agent_root), (run_root, runs_root)):
                if _user_store.lexists(path):
                    _user_store.require_real_directory(path, message="Run storage must be a real directory.")
                else:
                    _user_store.make_directory(path, parent=parent, message="Could not create run storage.")
            safe_summary = str(redact_value(summary).value)
            safe_message = str(redact_value(job.message).value)
            body = (
                f"# Run {job.run_id}\n\n"
                f"- task: {safe_message}\n"
                "- action: runtime\n"
                "- status: error\n"
                "- completed: false\n"
                f"- terminal_reason: {terminal_reason}\n"
                "- last_action: runtime\n"
                f"- last_observation_summary: {safe_summary}\n"
                f"- error: {terminal_reason.upper()}: {safe_summary}\n"
            )
            _user_store.atomic_replace_bytes(agent_root, run_root / "summary.md", body.encode("utf-8"))
        except _user_store.UserStoreError as exc:
            raise ChatJobStoreError("Could not write recovered run summary.") from exc


def _metadata_path(root: Path, job_id: str) -> Path:
    _validate_job_id(job_id)
    return root / f"{job_id}.json"


def _events_path(root: Path, job_id: str) -> Path:
    _validate_job_id(job_id)
    return root / f"{job_id}.events.jsonl"


def _validate_job_id(value: object) -> None:
    if not isinstance(value, str) or _JOB_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("chat job id is invalid.")


def _validate_metadata(record: Any, expected_job_id: str) -> None:
    if not isinstance(record, dict) or set(record) != _JOB_FIELDS or record.get("version") != _JOB_VERSION:
        raise ValueError("Chat job metadata has unknown or missing fields.")
    if record.get("job_id") != expected_job_id:
        raise ValueError("Chat job metadata id does not match its file name.")
    _validate_job_id(record["job_id"])
    if not isinstance(record.get("session_id"), str) or _SESSION_ID_PATTERN.fullmatch(record["session_id"]) is None:
        raise ValueError("Chat job session id is invalid.")
    if not isinstance(record.get("run_id"), str) or _RUN_ID_PATTERN.fullmatch(record["run_id"]) is None:
        raise ValueError("Chat job run id is invalid.")
    if record.get("status") not in {"running", "cancel_requested", *_TERMINAL_STATUSES}:
        raise ValueError("Chat job status is invalid.")
    if not isinstance(record.get("started_at"), str):
        raise ValueError("Chat job start time is invalid.")
    if record.get("completed_at") is not None and not isinstance(record["completed_at"], str):
        raise ValueError("Chat job completion time is invalid.")
    validate_timeout_seconds(record.get("timeout_seconds"))
    resumed_from = record.get("resumed_from_job_id")
    if resumed_from is not None:
        _validate_job_id(resumed_from)
    if not isinstance(record.get("message"), str):
        raise ValueError("Chat job message is invalid.")


def _last_terminal_status(events: list[dict[str, Any]]) -> str | None:
    statuses = [_TERMINAL_EVENTS[event["event"]] for event in events if event["event"] in _TERMINAL_EVENTS]
    if len(statuses) > 1:
        raise ValueError("Chat job event log contains multiple terminal events.")
    return statuses[0] if statuses else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
