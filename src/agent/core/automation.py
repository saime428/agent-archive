from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable, Iterator

from agent._user_store import (
    UserStoreError,
    atomic_replace_bytes,
    lexists,
    require_plain_file,
    require_real_directory,
    store_lock,
)
from agent.config import load_config
from agent.core.actions import ErrorCode
from agent.core.loop import run_once
from agent.core.redaction import redact_value
from agent.core.run_control import DEFAULT_RUN_TIMEOUT_SECONDS, RunControl, validate_timeout_seconds
from agent.core.run_lease import WorkspaceRunLease
from agent.core.skills import load_selected_skills
from agent.llm.factory import make_llm as make_llm_client
from agent.mcp_runtime import McpStdioRuntime
from agent.secrets import load_workspace_secrets


MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 365 * 24 * 60 * 60
MIN_POLL_SECONDS = 1
MAX_POLL_SECONDS = 3600
_MAX_TASK_CHARS = 20_000
_MAX_ERROR_CHARS = 2_000
_MAX_STORE_BYTES = 16 * 1024 * 1024
# ponytail: bounded whole-log rewrites keep local publication atomic; move to
# SQLite only if one workspace outgrows this personal-tool ceiling.
_MAX_SKILLS = 32
_AUTOMATION_ID_PATTERN = re.compile(r"auto_[a-f0-9]{32}\Z", re.ASCII)
_ATTEMPT_ID_PATTERN = re.compile(r"attempt_[a-f0-9]{32}\Z", re.ASCII)
_DEFINITION_STATUSES = {"disabled", "enabled"}
_RAW_ATTEMPT_STATUSES = {"claimed", "running", "succeeded", "failed", "cancelled", "timed_out", "interrupted"}
_TERMINAL_ATTEMPT_STATUSES = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
_ABNORMAL_ATTEMPT_STATUSES = _TERMINAL_ATTEMPT_STATUSES - {"succeeded"}


@dataclass(frozen=True)
class AutomationDefinition:
    automation_id: str
    task: str
    interval_seconds: int
    skills: tuple[str, ...]
    timeout_seconds: int
    status: str
    anchor_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AutomationAttempt:
    attempt_id: str
    automation_id: str
    scheduled_for: str
    run_id: str
    status: str
    created_at: str
    updated_at: str
    summary_path: str | None = None
    error: str | None = None
    notification: str | None = None


class AutomationError(ValueError):
    pass


class AutomationStore:
    def __init__(self, cwd: Path) -> None:
        self.workspace = cwd.resolve()
        self.agent_root = self.workspace / ".agent"
        self.root = self.agent_root / "automations"
        self.definitions_path = self.root / "definitions.jsonl"
        self.attempts_path = self.root / "attempts.jsonl"
        self.cancel_root = self.root / "cancel"
        self.worker_root = self.root / "worker"

    def add_definition(
        self,
        *,
        task: str,
        interval_seconds: int,
        skills: tuple[str, ...] = (),
        timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
        now: datetime | None = None,
    ) -> AutomationDefinition:
        task = _bounded_text(task, label="Automation task", max_chars=_MAX_TASK_CHARS)
        interval_seconds = _interval_seconds(interval_seconds)
        skills = _skills(skills)
        timeout_seconds = _timeout_seconds(timeout_seconds)
        timestamp = _timestamp(now)
        definition = AutomationDefinition(
            automation_id=f"auto_{uuid.uuid4().hex}",
            task=task,
            interval_seconds=interval_seconds,
            skills=skills,
            timeout_seconds=timeout_seconds,
            status="disabled",
            anchor_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._locked():
            definitions = self._read_definitions()
            self._write_jsonl(self.definitions_path, [*definitions, definition])
        return definition

    def list_definitions(self, *, include_history: bool = False) -> list[AutomationDefinition]:
        definitions = self._read_definitions()
        return definitions if include_history else _current_definitions(definitions)

    def get_definition(self, automation_id: str) -> AutomationDefinition:
        _require_id(automation_id, _AUTOMATION_ID_PATTERN, "automation")
        definition = next(
            (item for item in self.list_definitions() if item.automation_id == automation_id),
            None,
        )
        if definition is None:
            raise AutomationError(f"Unknown automation: {automation_id}")
        return definition

    def definition_history(self, automation_id: str) -> list[AutomationDefinition]:
        _require_id(automation_id, _AUTOMATION_ID_PATTERN, "automation")
        history = [item for item in self._read_definitions() if item.automation_id == automation_id]
        if not history:
            raise AutomationError(f"Unknown automation: {automation_id}")
        return history

    def enable_definition(
        self,
        automation_id: str,
        *,
        now: datetime | None = None,
    ) -> AutomationDefinition:
        return self._revise_definition(automation_id, status="enabled", now=now)

    def disable_definition(
        self,
        automation_id: str,
        *,
        now: datetime | None = None,
    ) -> AutomationDefinition:
        return self._revise_definition(automation_id, status="disabled", now=now)

    def _revise_definition(
        self,
        automation_id: str,
        *,
        status: str,
        now: datetime | None,
    ) -> AutomationDefinition:
        _require_id(automation_id, _AUTOMATION_ID_PATTERN, "automation")
        timestamp = _timestamp(now)
        with self._locked():
            definitions = self._read_definitions()
            current = next(
                (item for item in _current_definitions(definitions) if item.automation_id == automation_id),
                None,
            )
            if current is None:
                raise AutomationError(f"Unknown automation: {automation_id}")
            if current.status == status:
                raise AutomationError(f"Automation {automation_id} is already {status}.")
            revised = replace(
                current,
                status=status,
                anchor_at=timestamp if status == "enabled" else current.anchor_at,
                updated_at=timestamp,
            )
            self._write_jsonl(self.definitions_path, [*definitions, revised])
        return revised

    def claim_due(self, *, now: datetime | None = None) -> list[AutomationAttempt]:
        current_time = _utc_datetime(now)
        timestamp = current_time.isoformat()
        with self._locked():
            definitions = _current_definitions(self._read_definitions())
            attempts = self._read_attempts()
            current_attempts = _current_attempts(attempts)
            occupied_slots = {(item.automation_id, item.scheduled_for) for item in attempts}
            active_automations = {
                item.automation_id
                for item in current_attempts
                if item.status not in _TERMINAL_ATTEMPT_STATUSES
            }
            claimed: list[AutomationAttempt] = []
            for definition in definitions:
                if definition.status != "enabled" or definition.automation_id in active_automations:
                    continue
                scheduled_for = _due_slot(definition, current_time)
                if scheduled_for is None or (definition.automation_id, scheduled_for) in occupied_slots:
                    continue
                attempt = AutomationAttempt(
                    attempt_id=f"attempt_{uuid.uuid4().hex}",
                    automation_id=definition.automation_id,
                    scheduled_for=scheduled_for,
                    run_id=f"run_auto_{uuid.uuid4().hex}",
                    status="claimed",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                attempts.append(attempt)
                claimed.append(attempt)
            if claimed:
                self._write_jsonl(self.attempts_path, attempts)
        return claimed

    def list_attempts(
        self,
        *,
        automation_id: str | None = None,
        include_history: bool = False,
    ) -> list[AutomationAttempt]:
        if automation_id is not None:
            _require_id(automation_id, _AUTOMATION_ID_PATTERN, "automation")
        attempts = self._read_attempts()
        selected = attempts if include_history else _current_attempts(attempts)
        if not include_history:
            selected = [self._effective_attempt(item) for item in selected]
        if automation_id is not None:
            selected = [item for item in selected if item.automation_id == automation_id]
        return selected

    def get_attempt(self, attempt_id: str) -> AutomationAttempt:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        attempt = next((item for item in self.list_attempts() if item.attempt_id == attempt_id), None)
        if attempt is None:
            raise AutomationError(f"Unknown automation attempt: {attempt_id}")
        return attempt

    def mark_running(
        self,
        attempt_id: str,
        *,
        now: datetime | None = None,
    ) -> AutomationAttempt:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        timestamp = _timestamp(now)
        with self._locked():
            attempts = self._read_attempts()
            current = _find_attempt(_current_attempts(attempts), attempt_id)
            if current.status != "claimed":
                raise AutomationError(f"Automation attempt {attempt_id} cannot start from {current.status}.")
            if self.is_cancel_requested(attempt_id):
                raise AutomationError(f"Automation attempt {attempt_id} has a cancellation request.")
            running = replace(current, status="running", updated_at=timestamp)
            self._write_jsonl(self.attempts_path, [*attempts, running])
        return running

    def request_cancel(self, attempt_id: str) -> AutomationAttempt:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        with self._locked():
            current = _find_attempt(_current_attempts(self._read_attempts()), attempt_id)
            if current.status in _TERMINAL_ATTEMPT_STATUSES:
                raise AutomationError(f"Automation attempt {attempt_id} is already terminal.")
            self._prepare_child(self.cancel_root, create=True)
            marker = self._cancel_path(attempt_id)
            if lexists(marker):
                _require_marker(marker)
            else:
                try:
                    atomic_replace_bytes(self.root, marker, b"cancel_requested\n")
                except UserStoreError as exc:
                    raise AutomationError(_store_message(exc)) from exc
        return replace(current, status="cancel_requested")

    def is_cancel_requested(self, attempt_id: str) -> bool:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        if not self._prepare_root(create=False) or not self._prepare_child(self.cancel_root, create=False):
            return False
        marker = self._cancel_path(attempt_id)
        if not lexists(marker):
            return False
        _require_marker(marker)
        return True

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        summary_path: str | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> AutomationAttempt:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        if status not in _TERMINAL_ATTEMPT_STATUSES:
            raise AutomationError(f"Invalid terminal automation status: {status}")
        timestamp = _timestamp(now)
        summary_path = _optional_line(summary_path, label="Automation summary path", max_chars=1_024)
        error = _optional_text(error, label="Automation error", max_chars=_MAX_ERROR_CHARS)
        if status == "succeeded" and error is not None:
            raise AutomationError("Succeeded automation attempt cannot contain an error.")
        with self._locked():
            attempts = self._read_attempts()
            current = _find_attempt(_current_attempts(attempts), attempt_id)
            if current.status in _TERMINAL_ATTEMPT_STATUSES:
                raise AutomationError(f"Automation attempt {attempt_id} is already terminal.")
            if self.is_cancel_requested(attempt_id) and status not in {"cancelled", "timed_out"}:
                status = "cancelled"
                error = "Automation attempt was cancelled."
            if status != "succeeded" and error is None:
                error = f"Automation attempt ended with status {status}."
            notification = error if status in _ABNORMAL_ATTEMPT_STATUSES else None
            terminal = replace(
                current,
                status=status,
                updated_at=timestamp,
                summary_path=summary_path,
                error=error,
                notification=notification,
            )
            self._write_jsonl(self.attempts_path, [*attempts, terminal])
        return terminal

    def recover_incomplete(self, *, now: datetime | None = None) -> list[AutomationAttempt]:
        timestamp = _timestamp(now)
        with self._locked():
            attempts = self._read_attempts()
            recovered: list[AutomationAttempt] = []
            for current in _current_attempts(attempts):
                if current.status in _TERMINAL_ATTEMPT_STATUSES:
                    continue
                cancelled = self.is_cancel_requested(current.attempt_id)
                status = "cancelled" if cancelled else "interrupted"
                message = (
                    "Automation attempt was cancelled before recovery."
                    if cancelled
                    else "Automation worker stopped before the attempt reached a terminal state."
                )
                terminal = replace(
                    current,
                    status=status,
                    updated_at=timestamp,
                    error=message,
                    notification=message,
                )
                attempts.append(terminal)
                recovered.append(terminal)
            if recovered:
                self._write_jsonl(self.attempts_path, attempts)
        return recovered

    def list_notifications(self) -> list[AutomationAttempt]:
        return [
            item
            for item in self._read_attempts()
            if item.status in _ABNORMAL_ATTEMPT_STATUSES and item.notification is not None
        ]

    @contextmanager
    def worker_lock(self) -> Iterator[None]:
        self._prepare_root(create=True)
        self._prepare_child(self.worker_root, create=True)
        try:
            with store_lock(self.worker_root):
                yield
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._prepare_root(create=True)
        try:
            with store_lock(self.root):
                yield
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc

    def _prepare_root(self, *, create: bool) -> bool:
        try:
            if lexists(self.agent_root):
                require_real_directory(self.agent_root, message="Automation parent must be a real directory.")
            elif not create:
                return False
            else:
                self.agent_root.mkdir(parents=True, exist_ok=True)
            if lexists(self.root):
                require_real_directory(self.root, message="Automation root must be a real directory.")
            elif not create:
                return False
            else:
                self.root.mkdir()
            require_real_directory(self.agent_root, message="Automation parent must remain a real directory.")
            require_real_directory(self.root, message="Automation root must remain a real directory.")
            return True
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc
        except OSError as exc:
            raise AutomationError("Could not prepare automation storage.") from exc

    def _prepare_child(self, path: Path, *, create: bool) -> bool:
        if not self._prepare_root(create=create):
            return False
        try:
            if lexists(path):
                require_real_directory(path, message="Automation storage child must be a real directory.")
            elif not create:
                return False
            else:
                path.mkdir()
            require_real_directory(path, message="Automation storage child must remain a real directory.")
            return True
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc
        except OSError as exc:
            raise AutomationError("Could not prepare automation storage child.") from exc

    def _read_definitions(self) -> list[AutomationDefinition]:
        definitions = [_definition_from_record(item) for item in self._read_jsonl(self.definitions_path)]
        _validate_definition_history(definitions)
        return definitions

    def _read_attempts(self) -> list[AutomationAttempt]:
        attempts = [_attempt_from_record(item) for item in self._read_jsonl(self.attempts_path)]
        _validate_attempt_history(attempts)
        return attempts

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not self._prepare_root(create=False):
            return []
        try:
            if not lexists(path):
                return []
            require_plain_file(path, message="Automation log must be a regular file, not a link or reparse point.")
            if path.stat().st_size > _MAX_STORE_BYTES:
                raise AutomationError(f"Automation log is too large: {path.name}.")
            data = path.read_bytes()
            require_plain_file(path, message="Automation log must remain a regular file.")
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc
        except OSError as exc:
            raise AutomationError(f"Could not read automation log: {path.name}.") from exc
        if len(data) > _MAX_STORE_BYTES:
            raise AutomationError(f"Automation log is too large: {path.name}.")
        try:
            records = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutomationError(f"Could not parse automation log: {path.name}.") from exc
        if not all(isinstance(record, dict) for record in records):
            raise AutomationError(f"Could not parse automation log: {path.name}.")
        return records

    def _write_jsonl(
        self,
        path: Path,
        records: list[AutomationDefinition] | list[AutomationAttempt],
    ) -> None:
        data = "".join(
            json.dumps(asdict(record), ensure_ascii=True, separators=(",", ":")) + "\n"
            for record in records
        ).encode("utf-8")
        if len(data) > _MAX_STORE_BYTES:
            raise AutomationError(f"Automation log is too large: {path.name}.")
        try:
            atomic_replace_bytes(self.root, path, data)
        except UserStoreError as exc:
            raise AutomationError(_store_message(exc)) from exc

    def _cancel_path(self, attempt_id: str) -> Path:
        _require_id(attempt_id, _ATTEMPT_ID_PATTERN, "attempt")
        return self.cancel_root / attempt_id

    def _effective_attempt(self, attempt: AutomationAttempt) -> AutomationAttempt:
        if attempt.status not in _TERMINAL_ATTEMPT_STATUSES and self.is_cancel_requested(attempt.attempt_id):
            return replace(attempt, status="cancel_requested")
        return attempt


class AutomationWorker:
    def __init__(
        self,
        cwd: Path,
        *,
        llm_factory: Callable[[Any], Any] = make_llm_client,
        runtime_factory: Callable[[Path], Any] = McpStdioRuntime,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.workspace = cwd.resolve()
        self.store = AutomationStore(self.workspace)
        self._llm_factory = llm_factory
        self._runtime_factory = runtime_factory
        self._now = now

    def run_once(self, *, stop_requested: Callable[[], bool] = lambda: False) -> list[AutomationAttempt]:
        with self.store.worker_lock():
            completed = self.store.recover_incomplete(now=self._now())
            if stop_requested():
                return completed
            claims = self.store.claim_due(now=self._now())
            completed.extend(self._execute_claims(claims, stop_requested=stop_requested))
            return completed

    def run_forever(
        self,
        stop_event: Event,
        *,
        poll_seconds: int,
        on_attempt: Callable[[AutomationAttempt], None] | None = None,
    ) -> int:
        poll_seconds = _poll_seconds(poll_seconds)
        failures = 0
        with self.store.worker_lock():
            recovered = self.store.recover_incomplete(now=self._now())
            for attempt in recovered:
                failures += 1
                if on_attempt is not None:
                    on_attempt(attempt)
            while not stop_event.is_set():
                claims = self.store.claim_due(now=self._now())
                completed = self._execute_claims(claims, stop_requested=stop_event.is_set)
                for attempt in completed:
                    failures += int(attempt.status != "succeeded")
                    if on_attempt is not None:
                        on_attempt(attempt)
                if stop_event.wait(poll_seconds):
                    break
        return failures

    def _execute_claims(
        self,
        claims: list[AutomationAttempt],
        *,
        stop_requested: Callable[[], bool],
    ) -> list[AutomationAttempt]:
        completed: list[AutomationAttempt] = []
        for attempt in claims:
            if stop_requested() or self.store.is_cancel_requested(attempt.attempt_id):
                completed.append(
                    self.store.finish_attempt(
                        attempt.attempt_id,
                        status="cancelled",
                        error="Automation attempt was cancelled before execution.",
                        now=self._now(),
                    )
                )
                continue
            definition = self.store.get_definition(attempt.automation_id)
            if definition.status != "enabled":
                completed.append(
                    self.store.finish_attempt(
                        attempt.attempt_id,
                        status="cancelled",
                        error="Automation was disabled before execution.",
                        now=self._now(),
                    )
                )
                continue
            completed.append(self._execute(attempt, definition, stop_requested=stop_requested))
        return completed

    def _execute(
        self,
        attempt: AutomationAttempt,
        definition: AutomationDefinition,
        *,
        stop_requested: Callable[[], bool],
    ) -> AutomationAttempt:
        try:
            self.store.mark_running(attempt.attempt_id, now=self._now())
        except AutomationError as exc:
            return self.store.finish_attempt(
                attempt.attempt_id,
                status="failed",
                error=str(exc),
                now=self._now(),
            )
        probe_error: list[str] = []

        def cancel_probe() -> bool:
            if stop_requested():
                return True
            try:
                return self.store.is_cancel_requested(attempt.attempt_id)
            except AutomationError as exc:
                probe_error[:] = [str(exc)]
                return True

        control = RunControl.with_timeout(definition.timeout_seconds, cancel_probe=cancel_probe)
        result = None
        try:
            load_workspace_secrets(self.workspace)
            config, _diagnostics = load_config(self.workspace)
            if definition.skills:
                load_selected_skills(self.workspace, definition.skills, max_chars=_MAX_TASK_CHARS)
            with WorkspaceRunLease.acquire(
                self.workspace,
                owner={"kind": "automation", "attempt_id": attempt.attempt_id},
            ):
                runtime = self._runtime_factory(self.workspace)
                try:
                    llm = self._llm_factory(config)
                    result = run_once(
                        definition.task,
                        llm,
                        cwd=self.workspace,
                        run_id=attempt.run_id,
                        config=config,
                        selected_skills=definition.skills or None,
                        mcp_runtime=runtime,
                        approval_handler=None,
                        stream_handler=lambda _text: None,
                        control=control,
                    )
                finally:
                    runtime.close()
        except Exception as exc:
            return self.store.finish_attempt(
                attempt.attempt_id,
                status="failed",
                error=_exception_text(exc),
                now=self._now(),
            )

        summary_path = result.summary_path.relative_to(self.workspace).as_posix()
        if probe_error:
            return self.store.finish_attempt(
                attempt.attempt_id,
                status="failed",
                summary_path=summary_path,
                error=f"Automation cancellation check failed: {probe_error[0]}",
                now=self._now(),
            )
        error = result.observation.error
        error_code = error.code if error is not None else None
        if error_code == ErrorCode.CANCELLED:
            status = "cancelled"
        elif error_code == ErrorCode.TIMEOUT:
            status = "timed_out"
        elif result.action.action.name == "done" and result.observation.status == "ok":
            status = "succeeded"
        else:
            status = "failed"
        message = error.message if error is not None else result.observation.summary
        return self.store.finish_attempt(
            attempt.attempt_id,
            status=status,
            summary_path=summary_path,
            error=None if status == "succeeded" else message,
            now=self._now(),
        )


def _definition_from_record(record: dict[str, Any]) -> AutomationDefinition:
    expected = {
        "automation_id",
        "task",
        "interval_seconds",
        "skills",
        "timeout_seconds",
        "status",
        "anchor_at",
        "created_at",
        "updated_at",
    }
    if set(record) != expected:
        raise AutomationError("Could not parse automation definition record.")
    automation_id = _require_id(record["automation_id"], _AUTOMATION_ID_PATTERN, "automation")
    task = _bounded_text(record["task"], label="Automation task", max_chars=_MAX_TASK_CHARS)
    interval_seconds = _interval_seconds(record["interval_seconds"])
    skills = _skills(record["skills"])
    timeout_seconds = _timeout_seconds(record["timeout_seconds"])
    status = record["status"]
    if status not in _DEFINITION_STATUSES:
        raise AutomationError(f"Unknown automation definition status: {status!r}.")
    anchor_at = record["anchor_at"]
    if anchor_at is not None:
        anchor_at = _stored_timestamp(anchor_at)
    if status == "enabled" and anchor_at is None:
        raise AutomationError("Enabled automation must have an anchor time.")
    created_at = _stored_timestamp(record["created_at"])
    updated_at = _stored_timestamp(record["updated_at"])
    return AutomationDefinition(
        automation_id,
        task,
        interval_seconds,
        skills,
        timeout_seconds,
        status,
        anchor_at,
        created_at,
        updated_at,
    )


def _attempt_from_record(record: dict[str, Any]) -> AutomationAttempt:
    expected = {
        "attempt_id",
        "automation_id",
        "scheduled_for",
        "run_id",
        "status",
        "created_at",
        "updated_at",
        "summary_path",
        "error",
        "notification",
    }
    if set(record) != expected:
        raise AutomationError("Could not parse automation attempt record.")
    attempt_id = _require_id(record["attempt_id"], _ATTEMPT_ID_PATTERN, "attempt")
    automation_id = _require_id(record["automation_id"], _AUTOMATION_ID_PATTERN, "automation")
    scheduled_for = _stored_timestamp(record["scheduled_for"])
    run_id = _line(record["run_id"], label="Automation run id", max_chars=128)
    if not run_id.startswith("run_"):
        raise AutomationError("Invalid automation run id.")
    status = record["status"]
    if status not in _RAW_ATTEMPT_STATUSES:
        raise AutomationError(f"Unknown automation attempt status: {status!r}.")
    created_at = _stored_timestamp(record["created_at"])
    updated_at = _stored_timestamp(record["updated_at"])
    summary_path = _optional_line(record["summary_path"], label="Automation summary path", max_chars=1_024)
    error = _optional_text(record["error"], label="Automation error", max_chars=_MAX_ERROR_CHARS)
    notification = _optional_text(
        record["notification"],
        label="Automation notification",
        max_chars=_MAX_ERROR_CHARS,
    )
    if status == "succeeded" and (error is not None or notification is not None):
        raise AutomationError("Succeeded automation attempt cannot contain an error notification.")
    if status in _ABNORMAL_ATTEMPT_STATUSES and notification is None:
        raise AutomationError("Abnormal automation terminal must contain a notification.")
    if status not in _TERMINAL_ATTEMPT_STATUSES and any(
        value is not None for value in (summary_path, error, notification)
    ):
        raise AutomationError("Non-terminal automation attempt contains terminal fields.")
    return AutomationAttempt(
        attempt_id,
        automation_id,
        scheduled_for,
        run_id,
        status,
        created_at,
        updated_at,
        summary_path,
        error,
        notification,
    )


def _validate_definition_history(definitions: list[AutomationDefinition]) -> None:
    current: dict[str, AutomationDefinition] = {}
    for definition in definitions:
        previous = current.get(definition.automation_id)
        if previous is None:
            if definition.status != "disabled" or definition.anchor_at is not None:
                raise AutomationError("Automation definition history must start disabled.")
        else:
            immutable = ("task", "interval_seconds", "skills", "timeout_seconds", "created_at")
            if any(getattr(previous, field) != getattr(definition, field) for field in immutable):
                raise AutomationError(f"Automation definition {definition.automation_id} changed immutable fields.")
            if previous.status == definition.status:
                raise AutomationError(f"Automation definition {definition.automation_id} repeats status.")
        current[definition.automation_id] = definition


def _validate_attempt_history(attempts: list[AutomationAttempt]) -> None:
    current: dict[str, AutomationAttempt] = {}
    slots: dict[tuple[str, str], str] = {}
    for attempt in attempts:
        slot = (attempt.automation_id, attempt.scheduled_for)
        owner = slots.setdefault(slot, attempt.attempt_id)
        if owner != attempt.attempt_id:
            raise AutomationError(f"Duplicate automation attempt slot: {attempt.automation_id} {attempt.scheduled_for}")
        previous = current.get(attempt.attempt_id)
        if previous is None:
            if attempt.status != "claimed":
                raise AutomationError("Automation attempt history must start claimed.")
        else:
            immutable = ("automation_id", "scheduled_for", "run_id", "created_at")
            if any(getattr(previous, field) != getattr(attempt, field) for field in immutable):
                raise AutomationError(f"Automation attempt {attempt.attempt_id} changed immutable fields.")
            if previous.status in _TERMINAL_ATTEMPT_STATUSES:
                raise AutomationError(f"Automation attempt {attempt.attempt_id} has multiple terminal records.")
            if previous.status == "claimed" and attempt.status not in {"running", *_TERMINAL_ATTEMPT_STATUSES}:
                raise AutomationError(f"Automation attempt {attempt.attempt_id} has an invalid transition.")
            if previous.status == "running" and attempt.status not in _TERMINAL_ATTEMPT_STATUSES:
                raise AutomationError(f"Automation attempt {attempt.attempt_id} has an invalid transition.")
        current[attempt.attempt_id] = attempt


def _current_definitions(definitions: list[AutomationDefinition]) -> list[AutomationDefinition]:
    current: dict[str, AutomationDefinition] = {}
    for definition in definitions:
        current[definition.automation_id] = definition
    return list(current.values())


def _current_attempts(attempts: list[AutomationAttempt]) -> list[AutomationAttempt]:
    current: dict[str, AutomationAttempt] = {}
    for attempt in attempts:
        current[attempt.attempt_id] = attempt
    return list(current.values())


def _find_attempt(attempts: list[AutomationAttempt], attempt_id: str) -> AutomationAttempt:
    attempt = next((item for item in attempts if item.attempt_id == attempt_id), None)
    if attempt is None:
        raise AutomationError(f"Unknown automation attempt: {attempt_id}")
    return attempt


def _due_slot(definition: AutomationDefinition, now: datetime) -> str | None:
    if definition.anchor_at is None:
        return None
    anchor = _parse_timestamp(definition.anchor_at)
    if now < anchor:
        return None
    # ponytail: claim only the newest due slot; add backlog replay if users need
    # catch-up semantics rather than silently starting many stale tasks.
    slots = int((now - anchor).total_seconds() // definition.interval_seconds)
    return (anchor + timedelta(seconds=slots * definition.interval_seconds)).isoformat()


def _require_marker(path: Path) -> None:
    try:
        require_plain_file(path, message="Automation cancel marker must be a regular file.")
        if path.stat().st_size > 64 or path.read_bytes() != b"cancel_requested\n":
            raise AutomationError("Automation cancel marker is invalid.")
        require_plain_file(path, message="Automation cancel marker must remain a regular file.")
    except UserStoreError as exc:
        raise AutomationError(_store_message(exc)) from exc
    except OSError as exc:
        raise AutomationError("Could not read automation cancel marker.") from exc


def _interval_seconds(value: Any) -> int:
    if type(value) is not int or not MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
        raise AutomationError(
            f"interval_seconds must be an integer from {MIN_INTERVAL_SECONDS} to {MAX_INTERVAL_SECONDS}."
        )
    return value


def _poll_seconds(value: Any) -> int:
    if type(value) is not int or not MIN_POLL_SECONDS <= value <= MAX_POLL_SECONDS:
        raise AutomationError(f"poll_seconds must be an integer from {MIN_POLL_SECONDS} to {MAX_POLL_SECONDS}.")
    return value


def _timeout_seconds(value: Any) -> int:
    try:
        return validate_timeout_seconds(value)
    except ValueError as exc:
        raise AutomationError(str(exc)) from exc


def _skills(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_SKILLS:
        raise AutomationError("Automation skills must be a bounded list.")
    skills: list[str] = []
    for item in value:
        skill = _line(item, label="Automation skill", max_chars=128)
        if skill in skills:
            raise AutomationError(f"Duplicate automation skill: {skill}")
        skills.append(skill)
    return tuple(skills)


def _bounded_text(value: Any, *, label: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise AutomationError(f"{label} must be text.")
    redacted = redact_value(value).value
    if not redacted.strip():
        raise AutomationError(f"{label} cannot be empty.")
    if len(redacted) > max_chars:
        raise AutomationError(f"{label} is too large.")
    return redacted


def _optional_text(value: Any, *, label: str, max_chars: int) -> str | None:
    return None if value is None else _bounded_text(value, label=label, max_chars=max_chars)


def _line(value: Any, *, label: str, max_chars: int) -> str:
    text = _bounded_text(value, label=label, max_chars=max_chars)
    if any(character in text for character in "\0\r\n"):
        raise AutomationError(f"{label} must be one line.")
    return text


def _optional_line(value: Any, *, label: str, max_chars: int) -> str | None:
    return None if value is None else _line(value, label=label, max_chars=max_chars)


def _require_id(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AutomationError(f"Invalid {label} id.")
    return value


def _utc_datetime(value: datetime | None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise AutomationError("Automation time must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str:
    return _utc_datetime(value).isoformat()


def _stored_timestamp(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise AutomationError("Invalid automation timestamp.")
    _parse_timestamp(value)
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AutomationError("Invalid automation timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AutomationError("Automation timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _exception_text(exc: Exception) -> str:
    return _bounded_text(str(exc) or type(exc).__name__, label="Automation error", max_chars=_MAX_ERROR_CHARS)


def _store_message(exc: UserStoreError) -> str:
    return exc.message.replace("Extension", "Automation").replace("extension", "automation")
