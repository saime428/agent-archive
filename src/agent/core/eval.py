from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Callable

from agent._user_store import (
    UserStoreError,
    atomic_replace_json,
    lexists,
    require_real_directory,
)
from agent.config import AgentConfig
from agent.core.budget import TRUNCATION_MARKER, truncate_text
from agent.core.loop import run_once
from agent.core.redaction import redact_value
from agent.llm.fake import FakeLLMClient


_SCHEMA_VERSION = "agent-eval-v1"
_MAX_REPORT_BYTES = 256 * 1024
_MAX_DETAIL_CHARS = 2_000
_MAX_CASES = 32
_CASE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z", re.ASCII)


@dataclass(frozen=True)
class _EvalCase:
    case_id: str
    task: str
    fixtures: tuple[tuple[str, str], ...]
    actions: tuple[dict[str, Any], ...]
    expected_completed: bool
    expected_terminal_action: str
    expected_terminal_status: str
    expected_terminal_error: str | None
    expected_tool_calls: int
    expected_errors: int
    must_not_exist: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    completed: bool
    terminal_action: str | None
    terminal_status: str | None
    terminal_error: str | None
    tool_calls: int
    errors: int
    duration_ms: float
    run_id: str | None
    summary_path: str | None
    failure_detail: str | None


@dataclass(frozen=True)
class EvalReport:
    eval_id: str
    created_at: str
    duration_ms: float
    report_path: Path
    cases: tuple[EvalCaseResult, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def passed_cases(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def failed_cases(self) -> int:
        return self.total_cases - self.passed_cases

    @property
    def completed_cases(self) -> int:
        return sum(case.completed for case in self.cases)

    @property
    def tool_calls(self) -> int:
        return sum(case.tool_calls for case in self.cases)

    @property
    def errors(self) -> int:
        return sum(case.errors for case in self.cases)


class EvalError(ValueError):
    pass


_REFERENCE_CASES = (
    _EvalCase(
        case_id="direct_completion",
        task="Complete this deterministic eval case.",
        fixtures=(),
        actions=(),
        expected_completed=True,
        expected_terminal_action="done",
        expected_terminal_status="ok",
        expected_terminal_error=None,
        expected_tool_calls=0,
        expected_errors=0,
    ),
    _EvalCase(
        case_id="read_then_finish",
        task="Read notes.txt, then finish.",
        fixtures=(("notes.txt", "stable eval fixture\n"),),
        actions=(
            {
                "message": "Read the fixture.",
                "action": {
                    "name": "read_file",
                    "args": {"path": "notes.txt", "start_line": None, "max_lines": None},
                },
            },
        ),
        expected_completed=True,
        expected_terminal_action="done",
        expected_terminal_status="ok",
        expected_terminal_error=None,
        expected_tool_calls=1,
        expected_errors=0,
    ),
    _EvalCase(
        case_id="recover_after_missing_file",
        task="Recover from a missing file, read notes.txt, then finish.",
        fixtures=(("notes.txt", "recovery fixture\n"),),
        actions=(
            {
                "message": "Read a missing file.",
                "action": {
                    "name": "read_file",
                    "args": {"path": "missing.txt", "start_line": None, "max_lines": None},
                },
            },
            {
                "message": "Use the existing fixture instead.",
                "action": {
                    "name": "read_file",
                    "args": {"path": "notes.txt", "start_line": None, "max_lines": None},
                },
            },
        ),
        expected_completed=True,
        expected_terminal_action="done",
        expected_terminal_status="ok",
        expected_terminal_error=None,
        expected_tool_calls=2,
        expected_errors=1,
    ),
    _EvalCase(
        case_id="approval_stays_blocked",
        task="Attempt a write without an approval handler.",
        fixtures=(),
        actions=(
            {
                "message": "Write a file.",
                "action": {
                    "name": "write_file",
                    "args": {"path": "blocked.txt", "content": "must not exist\n", "create_parents": False},
                },
            },
        ),
        expected_completed=False,
        expected_terminal_action="write_file",
        expected_terminal_status="error",
        expected_terminal_error="APPROVAL_REQUIRED",
        expected_tool_calls=1,
        expected_errors=1,
        must_not_exist=("blocked.txt",),
    ),
)


def run_reference_eval(
    cwd: Path,
    *,
    clock: Callable[[], float] = perf_counter,
) -> EvalReport:
    workspace = cwd.resolve()
    cases = _validated_cases(_REFERENCE_CASES)
    eval_id = f"eval_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc).isoformat()
    eval_dir = _prepare_eval_directory(workspace, eval_id)
    started = clock()
    results = tuple(_run_case(case, eval_dir, clock=clock) for case in cases)
    duration_ms = _duration_ms(clock() - started)
    report_path = eval_dir / "report.json"
    report = EvalReport(eval_id, created_at, duration_ms, report_path, results)
    try:
        atomic_replace_json(eval_dir, report_path, _report_record(report), max_bytes=_MAX_REPORT_BYTES)
    except UserStoreError as exc:
        raise EvalError("Could not publish eval report.") from exc
    return report


def deterministic_signature(report: EvalReport) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            case.case_id,
            case.passed,
            case.completed,
            case.terminal_action,
            case.terminal_status,
            case.terminal_error,
            case.tool_calls,
            case.errors,
        )
        for case in report.cases
    )


def _run_case(
    case: _EvalCase,
    eval_dir: Path,
    *,
    clock: Callable[[], float],
) -> EvalCaseResult:
    started = clock()
    case_workspace = eval_dir / "cases" / case.case_id
    try:
        case_workspace.mkdir(parents=True)
        for relative_path, content in case.fixtures:
            fixture = _case_path(case_workspace, relative_path)
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(content, encoding="utf-8")
        result = run_once(
            case.task,
            FakeLLMClient(actions=copy.deepcopy(list(case.actions))),
            cwd=case_workspace,
            config=AgentConfig(provider="fake", default_skills=(), mode="auto"),
            approval_handler=None,
        )
        completed = result.action.action.name == "done" and result.observation.status == "ok"
        terminal_error = result.observation.error.code.value if result.observation.error is not None else None
        tool_calls = _tool_call_count(result.tool_calls_path)
        errors = sum(observation.status == "error" for observation in result.observations)
        observed = {
            "completed": completed,
            "terminal_action": result.action.action.name,
            "terminal_status": result.observation.status,
            "terminal_error": terminal_error,
            "tool_calls": tool_calls,
            "errors": errors,
        }
        expected = {
            "completed": case.expected_completed,
            "terminal_action": case.expected_terminal_action,
            "terminal_status": case.expected_terminal_status,
            "terminal_error": case.expected_terminal_error,
            "tool_calls": case.expected_tool_calls,
            "errors": case.expected_errors,
        }
        mismatches = [
            f"{name}: expected {expected[name]!r}, got {observed[name]!r}"
            for name in expected
            if observed[name] != expected[name]
        ]
        for relative_path in case.must_not_exist:
            if _case_path(case_workspace, relative_path).exists():
                mismatches.append(f"forbidden file exists: {relative_path}")
        return EvalCaseResult(
            case_id=case.case_id,
            passed=not mismatches,
            completed=completed,
            terminal_action=result.action.action.name,
            terminal_status=result.observation.status,
            terminal_error=terminal_error,
            tool_calls=tool_calls,
            errors=errors,
            duration_ms=_duration_ms(clock() - started),
            run_id=result.context.run_id,
            summary_path=result.summary_path.relative_to(eval_dir).as_posix(),
            failure_detail=_safe_detail("; ".join(mismatches)) if mismatches else None,
        )
    except Exception as exc:
        return EvalCaseResult(
            case_id=case.case_id,
            passed=False,
            completed=False,
            terminal_action=None,
            terminal_status=None,
            terminal_error=None,
            tool_calls=0,
            errors=0,
            duration_ms=_duration_ms(clock() - started),
            run_id=None,
            summary_path=None,
            failure_detail=_safe_detail(f"Case execution failed: {_exception_text(exc)}"),
        )


def _validated_cases(cases: tuple[_EvalCase, ...]) -> tuple[_EvalCase, ...]:
    if not 1 <= len(cases) <= _MAX_CASES:
        raise EvalError("Eval reference set must contain a bounded number of cases.")
    seen: set[str] = set()
    for case in cases:
        if _CASE_ID_PATTERN.fullmatch(case.case_id) is None or case.case_id in seen:
            raise EvalError(f"Invalid or duplicate eval case id: {case.case_id!r}.")
        seen.add(case.case_id)
        if not case.task.strip() or len(case.task) > 20_000:
            raise EvalError(f"Invalid eval task for case {case.case_id}.")
        if len(case.actions) > 10 or case.expected_tool_calls < 0 or case.expected_errors < 0:
            raise EvalError(f"Invalid eval expectations for case {case.case_id}.")
        fixture_paths = [_safe_relative_path(path) for path, _content in case.fixtures]
        forbidden_paths = [_safe_relative_path(path) for path in case.must_not_exist]
        if len(set(fixture_paths)) != len(fixture_paths) or set(fixture_paths) & set(forbidden_paths):
            raise EvalError(f"Invalid eval fixture paths for case {case.case_id}.")
        if any(not isinstance(content, str) or len(content) > 20_000 for _path, content in case.fixtures):
            raise EvalError(f"Invalid eval fixture content for case {case.case_id}.")
    return cases


def _prepare_eval_directory(workspace: Path, eval_id: str) -> Path:
    agent_root = workspace / ".agent"
    evals_root = agent_root / "evals"
    eval_dir = evals_root / eval_id
    try:
        require_real_directory(workspace, message="Eval workspace must be a real directory.")
        for path in (agent_root, evals_root):
            if lexists(path):
                require_real_directory(path, message="Eval storage must be a real directory, not a link or reparse point.")
            else:
                path.mkdir()
            require_real_directory(path, message="Eval storage must remain a real directory.")
        eval_dir.mkdir()
        require_real_directory(eval_dir, message="Eval run storage must be a real directory.")
        return eval_dir
    except UserStoreError as exc:
        raise EvalError(exc.message) from exc
    except OSError as exc:
        raise EvalError("Could not prepare eval storage.") from exc


def _case_path(workspace: Path, relative_path: str) -> Path:
    return workspace.joinpath(*_safe_relative_path(relative_path).parts)


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value or len(value) > 256:
        raise EvalError("Eval case path must be a bounded POSIX relative path.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise EvalError("Eval case path must be a bounded POSIX relative path.")
    return path


def _tool_call_count(path: Path) -> int:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    names = [record["action"]["action"]["name"] for record in records]
    if not all(isinstance(name, str) for name in names):
        raise EvalError("Eval tool trace contains an invalid action name.")
    return sum(name not in {"done", "ask_user"} for name in names)


def _report_record(report: EvalReport) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "eval_id": report.eval_id,
        "created_at": report.created_at,
        "passed": report.passed,
        "totals": {
            "cases": report.total_cases,
            "passed": report.passed_cases,
            "failed": report.failed_cases,
            "completed": report.completed_cases,
            "tool_calls": report.tool_calls,
            "errors": report.errors,
            "duration_ms": report.duration_ms,
        },
        "cases": [asdict(case) for case in report.cases],
    }


def _duration_ms(seconds: float) -> float:
    return round(max(0.0, seconds * 1_000), 3)


def _safe_detail(value: str) -> str:
    redacted = redact_value(value).value
    if len(redacted) <= _MAX_DETAIL_CHARS:
        return redacted
    return truncate_text(redacted, _MAX_DETAIL_CHARS - len(TRUNCATION_MARKER)).value


def _exception_text(exc: Exception) -> str:
    try:
        text = str(exc)
    except Exception:
        return type(exc).__name__
    return text if text.strip() else type(exc).__name__
