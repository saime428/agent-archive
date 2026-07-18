from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from agent.config import load_config
from agent.core.chat import ChatSession
from agent.llm.factory import make_llm
from agent.secrets import load_workspace_secrets
from agent.web import chats


CHAT_JOB_TTL_SECONDS = 300.0
APPROVAL_WAIT_TIMEOUT_SECONDS = CHAT_JOB_TTL_SECONDS
STREAM_EVENT_BATCH_CHARS = 64


@dataclass
class _ChatJob:
    job_id: str
    started_at: float
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    approval_pending: bool = False
    approval_deadline: float | None = None
    approval_decision: bool | Literal["timed_out"] | None = None
    done: bool = False
    completed_at: float | None = None


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
        self._jobs_lock = threading.Lock()

    def start(self, *, message: str, session_id: str | None) -> dict[str, Any]:
        self._prune()
        load_workspace_secrets(self._workspace)
        config, diagnostics = load_config(self._workspace)
        state = chats.load_or_create_chat_state(self._workspace, session_id)
        job = _ChatJob(job_id=f"job_{uuid.uuid4().hex[:12]}", started_at=self._clock())
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        self._append_event(job, {"event": "chat_started", "session_id": state.session_id})
        thread = threading.Thread(
            target=self._run_job,
            args=(job, state, config, diagnostics, message),
            daemon=True,
            name=f"chat-job-{job.job_id}",
        )
        try:
            thread.start()
        except Exception:
            with self._jobs_lock:
                if self._jobs.get(job.job_id) is job:
                    del self._jobs[job.job_id]
            raise
        return {"status": "running", "job_id": job.job_id, "session_id": state.session_id}

    def poll(self, job_id: str, *, after: int = 0, timeout: float = 0.0) -> dict[str, Any]:
        self._prune()
        if after < 0:
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
            }

    def decide(self, *, job_id: str, approve: bool) -> dict[str, Any]:
        self._prune()
        job = self._get_job(job_id)
        with job.condition:
            if job.done:
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
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown chat job: {job_id}")
        return job

    def _append_event(self, job: _ChatJob, event: dict[str, Any]) -> None:
        with job.condition:
            now = self._clock()
            if event.get("event") == "approval_required":
                job.approval_pending = True
                job.approval_deadline = now + self._approval_timeout
            record = dict(event)
            record["sequence"] = len(job.events)
            record["elapsed_ms"] = int((now - job.started_at) * 1000)
            job.events.append(record)
            job.condition.notify_all()

    def _run_job(self, job: _ChatJob, state: Any, config: Any, diagnostics: Any, message: str) -> None:
        pending_stream_event: dict[str, Any] | None = None

        def flush_stream_event() -> None:
            nonlocal pending_stream_event
            if pending_stream_event is not None:
                self._append_event(job, pending_stream_event)
                pending_stream_event = None

        def handle_event(event: dict[str, Any]) -> None:
            nonlocal pending_stream_event
            if event.get("event") == "model_stream_chunk":
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

        def handle_approval(_action: Any) -> bool | Literal["timed_out"]:
            with job.condition:
                while job.approval_decision is None and job.approval_pending and not job.done:
                    deadline = job.approval_deadline
                    remaining = (deadline - self._clock()) if deadline is not None else 0.0
                    if remaining <= 0:
                        job.approval_pending = False
                        job.approval_deadline = None
                        return "timed_out"
                    job.condition.wait(remaining)
                decision = job.approval_decision
                job.approval_decision = None
                job.approval_pending = False
                job.approval_deadline = None
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
                message,
                approval_handler=handle_approval,
                event_handler=handle_event,
                stream_handler=lambda _text: None,
            )
            payload = chats.build_chat_turn_response(self._workspace, session, result, diagnostics)
            handle_event({"event": "final", **payload})
        except Exception as exc:  # pragma: no cover - kept visible through SSE for local UI failures
            handle_event({"event": "error", "error": str(exc)})
        finally:
            with job.condition:
                job.approval_pending = False
                job.approval_deadline = None
                job.done = True
                job.completed_at = self._clock()
                job.condition.notify_all()
