from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.core.actions import Observation


REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "credential",
    "credentials",
    "private_key",
}
_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_token",
    "_secret",
    "_password",
    "_credential",
    "_credentials",
    "_private_key",
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b"),
    re.compile(r"\bAuthorization:\s*[^\r\n]+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{2,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    replacements: int

    @property
    def applied(self) -> bool:
        return self.replacements > 0


def redact_record(record: dict[str, Any]) -> RedactionResult:
    return redact_value(record)


def redact_observation(observation: Observation) -> RedactionResult:
    result = redact_value(
        {
            "summary": observation.summary,
            "data": observation.data,
            "error": observation.error.model_dump(mode="python") if observation.error is not None else None,
        }
    )
    value = result.value
    error = observation.error
    if error is not None:
        error = error.model_copy(
            update={
                "message": value["error"]["message"],
                "details": value["error"]["details"],
            }
        )
    return RedactionResult(
        observation.model_copy(
            update={
                "summary": value["summary"],
                "data": value["data"],
                "error": error,
            }
        ),
        result.replacements,
    )


def redact_value(value: Any) -> RedactionResult:
    return _redact_value(value, parent_key=None)


def _redact_value(value: Any, *, parent_key: str | None) -> RedactionResult:
    if parent_key is not None and _is_sensitive_key(parent_key) and value is not None:
        return RedactionResult(REDACTED, 1)

    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        replacements = 0
        for key, item in value.items():
            result = _redact_value(item, parent_key=str(key))
            redacted[key] = result.value
            replacements += result.replacements
        return RedactionResult(redacted, replacements)

    if isinstance(value, list):
        redacted_list = []
        replacements = 0
        for item in value:
            result = _redact_value(item, parent_key=None)
            redacted_list.append(result.value)
            replacements += result.replacements
        return RedactionResult(redacted_list, replacements)

    if isinstance(value, tuple):
        redacted_items = []
        replacements = 0
        for item in value:
            result = _redact_value(item, parent_key=None)
            redacted_items.append(result.value)
            replacements += result.replacements
        return RedactionResult(tuple(redacted_items), replacements)

    if isinstance(value, str):
        return _redact_string(value)

    return RedactionResult(value, 0)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return (
        normalized in _SENSITIVE_KEYS
        or compact in _SENSITIVE_KEYS
        or normalized.startswith("authorization_")
        or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)
        or compact.endswith(("token", "secret", "password", "credential", "credentials", "privatekey"))
    )


def _redact_string(value: str) -> RedactionResult:
    redacted = value
    replacements = 0
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(REDACTED, redacted)
        replacements += count
    return RedactionResult(redacted, replacements)
