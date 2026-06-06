from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


ACTION_PROTOCOL_VERSION = "agent-action-v1"
OBSERVATION_PROTOCOL_VERSION = "agent-observation-v1"


class ErrorCode(StrEnum):
    INVALID_JSON = "INVALID_JSON"
    UNSUPPORTED_PROTOCOL_VERSION = "UNSUPPORTED_PROTOCOL_VERSION"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SANDBOX_VIOLATION = "SANDBOX_VIOLATION"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    POLICY_DENIED = "POLICY_DENIED"
    TOOL_FAILED = "TOOL_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ActionParseError(ValueError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DoneArgs(StrictModel):
    final: str
    changed_files: list[str]
    next_steps: list[str]


class AskUserArgs(StrictModel):
    question: str
    options: list[str]
    reason: str


class ListDirArgs(StrictModel):
    path: str
    max_entries: int | None = None


class ReadFileArgs(StrictModel):
    path: str
    start_line: int | None = None
    max_lines: int | None = None


class SearchFilesArgs(StrictModel):
    query: str
    path: str | None = None
    max_matches: int | None = None


class WriteFileArgs(StrictModel):
    path: str
    content: str
    create_parents: bool


class PatchEditArgs(StrictModel):
    path: str
    old: str
    new: str
    occurrence: Literal["first", "all"] = "first"

    @field_validator("path", "old")
    @classmethod
    def _reject_empty_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be empty.")
        return value


class ApplyPatchArgs(StrictModel):
    edits: list[PatchEditArgs]

    @field_validator("edits")
    @classmethod
    def _reject_empty_edits(cls, value: list[PatchEditArgs]) -> list[PatchEditArgs]:
        if not value:
            raise ValueError("At least one edit is required.")
        return value


class RunCommandArgs(StrictModel):
    argv: list[str]
    cwd: str | None = None
    timeout_seconds: int | None = None

    @field_validator("argv")
    @classmethod
    def _reject_empty_argv(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("argv must not be empty.")
        if any(not item.strip() for item in value):
            raise ValueError("argv items must not be empty.")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _reject_invalid_timeout(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("timeout_seconds must be positive.")
        return value


ARGS_MODELS: dict[str, type[StrictModel]] = {
    "done": DoneArgs,
    "ask_user": AskUserArgs,
    "list_dir": ListDirArgs,
    "read_file": ReadFileArgs,
    "search_files": SearchFilesArgs,
    "write_file": WriteFileArgs,
    "apply_patch": ApplyPatchArgs,
    "run_command": RunCommandArgs,
}

TRUSTED_TOP_LEVEL_KEYS = {"message", "action"}
MODEL_METADATA_KEYS = {
    "protocol_version",
    "run_id",
    "action_id",
    "created_at",
}


class ActionCall(StrictModel):
    name: str
    args: dict[str, Any]


class InternalAction(StrictModel):
    protocol_version: Literal["agent-action-v1"] = ACTION_PROTOCOL_VERSION
    run_id: str
    action_id: str
    created_at: datetime
    message: str
    action: ActionCall


class ErrorInfo(StrictModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class Observation(StrictModel):
    protocol_version: Literal["agent-observation-v1"] = OBSERVATION_PROTOCOL_VERSION
    run_id: str
    action_id: str
    observation_id: str
    created_at: datetime
    status: Literal["ok", "error"]
    error: ErrorInfo | None
    summary: str
    data: dict[str, Any] | None = None


def parse_model_action(
    raw: str | dict[str, Any],
    *,
    run_id: str,
    action_index: int,
    created_at: datetime,
) -> InternalAction:
    raw_obj = _load_raw_action(raw)
    _validate_top_level_shape(raw_obj)

    action_obj = raw_obj["action"]
    _validate_action_shape(action_obj)

    name = action_obj["name"]
    if name not in ARGS_MODELS:
        raise ActionParseError(
            ErrorCode.UNKNOWN_TOOL,
            f"Unknown tool: {name}",
            {"tool": name},
        )

    args = _validate_args(name, action_obj["args"])

    return InternalAction(
        run_id=run_id,
        action_id=_format_action_id(action_index),
        created_at=created_at,
        message=raw_obj["message"],
        action=ActionCall(name=name, args=args),
    )


def make_observation(
    action: InternalAction,
    *,
    observation_index: int,
    summary: str,
    data: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        run_id=action.run_id,
        action_id=action.action_id,
        observation_id=_format_observation_id(observation_index),
        created_at=_now_utc(),
        status="ok",
        error=None,
        summary=summary,
        data=data,
    )


def make_error_observation(
    action_id: str,
    run_id: str,
    *,
    observation_index: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        run_id=run_id,
        action_id=action_id,
        observation_id=_format_observation_id(observation_index),
        created_at=_now_utc(),
        status="error",
        error=ErrorInfo(code=code, message=message, details=details),
        summary=message,
        data=None,
    )


def _load_raw_action(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ActionParseError(
                ErrorCode.INVALID_JSON,
                "Model response is not valid JSON.",
                {"error": str(exc)},
            ) from exc
    else:
        loaded = raw

    if not isinstance(loaded, dict):
        raise ActionParseError(
            ErrorCode.INVALID_ARGUMENT,
            "Model response must be a JSON object.",
        )

    return loaded


def _validate_top_level_shape(raw_obj: dict[str, Any]) -> None:
    missing = TRUSTED_TOP_LEVEL_KEYS - raw_obj.keys()
    if missing:
        raise ActionParseError(
            ErrorCode.MISSING_REQUIRED_FIELD,
            "Model response is missing required fields.",
            {"missing": sorted(missing)},
        )

    extras = set(raw_obj) - TRUSTED_TOP_LEVEL_KEYS - MODEL_METADATA_KEYS
    if extras:
        raise ActionParseError(
            ErrorCode.INVALID_ARGUMENT,
            "Model response contains unsupported fields.",
            {"extra": sorted(extras)},
        )

    if not isinstance(raw_obj["message"], str):
        raise ActionParseError(
            ErrorCode.INVALID_ARGUMENT,
            "Model response message must be a string.",
        )

    if not isinstance(raw_obj["action"], dict):
        raise ActionParseError(
            ErrorCode.INVALID_ARGUMENT,
            "Model response action must be an object.",
        )


def _validate_action_shape(action_obj: dict[str, Any]) -> None:
    missing = {"name", "args"} - action_obj.keys()
    if missing:
        raise ActionParseError(
            ErrorCode.MISSING_REQUIRED_FIELD,
            "Action is missing required fields.",
            {"missing": sorted(missing)},
        )

    extras = set(action_obj) - {"name", "args"}
    if extras:
        raise ActionParseError(
            ErrorCode.INVALID_ARGUMENT,
            "Action contains unsupported fields.",
            {"extra": sorted(extras)},
        )

    if not isinstance(action_obj["name"], str):
        raise ActionParseError(ErrorCode.INVALID_ARGUMENT, "Action name must be a string.")

    if not isinstance(action_obj["args"], dict):
        raise ActionParseError(ErrorCode.INVALID_ARGUMENT, "Action args must be an object.")


def _validate_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    model = ARGS_MODELS[name]
    try:
        parsed = model.model_validate(args)
    except ValidationError as exc:
        error_types = {error["type"] for error in exc.errors()}
        code = (
            ErrorCode.MISSING_REQUIRED_FIELD
            if "missing" in error_types
            else ErrorCode.INVALID_ARGUMENT
        )
        raise ActionParseError(
            code,
            f"Invalid args for action: {name}",
            {"errors": exc.errors()},
        ) from exc

    return parsed.model_dump()


def _format_action_id(action_index: int) -> str:
    return f"act_{action_index:06d}"


def _format_observation_id(observation_index: int) -> str:
    return f"obs_{observation_index:06d}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
