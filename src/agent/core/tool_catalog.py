from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Literal

from pydantic import ValidationError

from agent.core.actions import ARG_ALIASES, ARGS_MODELS


ToolRisk = Literal["terminal", "low-risk", "confirmation-required"]
DryRunBehavior = Literal["executes", "skipped"]
ToolSource = Literal["builtin", "mcp"]

_MAX_MCP_TOOLS = 64
_MAX_MCP_SCHEMA_BYTES = 512 * 1024
_MAX_MCP_MODEL_PAYLOAD_BYTES = 128 * 1024
_MAX_DESCRIPTION_CHARS = 1000
_PUBLIC_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_DESCRIPTION_TRUNCATION_MARKER = "? [truncated]"

_TERMINAL_TOOLS = {"done", "ask_user"}
_LOW_RISK_TOOLS = {
    "list_dir",
    "read_file",
    "read_pdf",
    "read_docx",
    "read_xlsx",
    "read_pptx",
    "search_files",
    "web_search",
    "git_status",
    "git_diff",
}
_CONFIRMATION_REQUIRED_TOOLS = {
    "write_file",
    "apply_patch",
    "run_command",
    "write_markdown_report",
}
_BUILTIN_DRY_RUN_SKIPPED = {
    "write_file",
    "apply_patch",
    "run_command",
    "write_markdown_report",
}

MODEL_TOOL_DESCRIPTIONS: dict[str, str] = {
    "done": "Finish the task and return the final user-facing answer.",
    "ask_user": "Ask the user a clarifying question when you cannot proceed.",
    "list_dir": "List entries in a directory.",
    "read_file": "Read a text file, optionally from a start line with a line limit.",
    "search_files": "Search file contents in the workspace for a query string.",
    "web_search": "Search the web for current information.",
    "write_file": "Create or overwrite a text file with the given content.",
    "apply_patch": "Apply one or more exact string-replacement edits to files.",
    "run_command": "Run an allowed command without a shell.",
    "git_status": "Show git status for the workspace.",
    "git_diff": "Show a git diff, optionally for one path or the staged index.",
    "read_pdf": "Extract text from a PDF file.",
    "read_docx": "Extract text from a Word document.",
    "read_xlsx": "Extract text from an Excel workbook.",
    "read_pptx": "Extract text from a PowerPoint file.",
    "write_markdown_report": "Write a Markdown report file with title, body, and sources.",
}

TOOL_DESCRIPTIONS = {
    "done": "Finish the run with a final response.",
    "ask_user": "Stop and return a structured user question.",
    "list_dir": "List workspace directory entries.",
    "read_file": "Read a workspace text file.",
    "read_pdf": "Extract text from a workspace PDF as untrusted source material.",
    "read_docx": "Extract text from a workspace DOCX as untrusted source material.",
    "read_xlsx": "Extract sheet summaries from a workspace XLSX as untrusted source material.",
    "read_pptx": "Extract slide text from a workspace PPTX as untrusted source material.",
    "write_markdown_report": "Write a source-grounded Markdown report with snapshot protection.",
    "search_files": "Search workspace paths and text.",
    "web_search": "Search the public web when enabled in Settings.",
    "write_file": "Write a workspace text file with snapshot protection.",
    "apply_patch": "Apply structured text replacements with snapshots.",
    "run_command": "Run an allowed structured argv command.",
    "git_status": "Show repository status.",
    "git_diff": "Show repository diff.",
}


class ToolCatalogError(ValueError):
    pass


class ToolArgumentError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        missing: bool = False,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing
        self.details = details or []


@dataclass(frozen=True, slots=True)
class ToolInfo:
    name: str
    category: str
    dry_run: str
    description: str


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    risk: ToolRisk
    dry_run: DryRunBehavior
    source: ToolSource
    target: object | None
    _validator: object
    _validator_fingerprint: str | None
    _aliases: Mapping[str, str]
    _schema_bytes: int = 0

    @property
    def server_id(self) -> str | None:
        return str(getattr(self.target, "server_id", "")) or None

    @property
    def remote_name(self) -> str | None:
        return str(getattr(self.target, "remote_name", "")) or None

    def input_schema_dict(self) -> dict[str, Any]:
        value = _thaw_json(self.input_schema)
        assert isinstance(value, dict)
        return value

    def model_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema_dict(),
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.source == "builtin":
            normalized = dict(arguments)
            for alias, target in self._aliases.items():
                if alias in normalized and target not in normalized:
                    normalized[target] = normalized.pop(alias)
            try:
                parsed = self._validator.model_validate(normalized)
            except ValidationError as exc:
                errors = exc.errors()
                raise ToolArgumentError(
                    f"Invalid args for action: {self.name}",
                    missing=any(error["type"] == "missing" for error in errors),
                    details=errors,
                ) from None
            return parsed.model_dump()

        try:
            current_fingerprint = _fingerprint_json(getattr(self._validator, "schema"))
        except Exception:
            current_fingerprint = None
        if current_fingerprint != self._validator_fingerprint:
            raise ToolArgumentError("MCP validator contract changed after catalog creation.")

        try:
            public_arguments = _clone_json(arguments)
        except (RecursionError, TypeError, ValueError):
            raise ToolArgumentError("MCP tool arguments must be bounded JSON data.") from None
        if not isinstance(public_arguments, dict):
            raise ToolArgumentError("MCP tool arguments must be an object.")

        details: list[dict[str, Any]] = []
        missing = False
        try:
            for error in self._validator.iter_errors(public_arguments):
                validator = str(getattr(error, "validator", "unknown"))
                missing = missing or validator == "required"
                details.append(
                    {
                        "path": _validation_path(getattr(error, "absolute_path", ())),
                        "validator": validator[:128],
                    }
                )
                if len(details) >= 8:
                    break
        except Exception:
            raise ToolArgumentError("MCP validator failed closed.") from None
        if details:
            raise ToolArgumentError(
                f"Invalid args for action: {self.name}",
                missing=missing,
                details=details,
            )
        return public_arguments


@dataclass(frozen=True, slots=True, init=False)
class ToolCatalog:
    definitions: tuple[ToolDefinition, ...]
    _by_name: Mapping[str, ToolDefinition]
    mcp_schema_bytes: int
    mcp_model_payload_bytes: int

    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        frozen = tuple(definitions)
        by_name: dict[str, ToolDefinition] = {}
        normalized_names: dict[str, str] = {}
        mcp_definitions = []
        schema_bytes = 0
        for definition in frozen:
            if not isinstance(definition, ToolDefinition):
                raise ToolCatalogError("Tool catalog contains an incomplete definition.")
            if definition.name in by_name:
                raise ToolCatalogError(f"Tool public name conflict: {definition.name}.")
            normalized = _normalized_public_name(definition.name)
            previous = normalized_names.get(normalized)
            if previous is not None:
                raise ToolCatalogError(
                    f"Tool normalized name conflict: {previous} and {definition.name}."
                )
            normalized_names[normalized] = definition.name
            by_name[definition.name] = definition
            if definition.source == "mcp":
                mcp_definitions.append(definition)
                schema_bytes += definition._schema_bytes

        if len(mcp_definitions) > _MAX_MCP_TOOLS:
            raise ToolCatalogError(f"At most {_MAX_MCP_TOOLS} MCP tools may be registered.")
        if schema_bytes > _MAX_MCP_SCHEMA_BYTES:
            raise ToolCatalogError("MCP total schema budget exceeds 512 KiB.")

        payload = [definition.model_schema() for definition in mcp_definitions]
        payload_bytes = (
            len(_canonical_json_bytes(payload)) if mcp_definitions else 0
        )
        if payload_bytes > _MAX_MCP_MODEL_PAYLOAD_BYTES:
            raise ToolCatalogError("MCP model-visible payload exceeds 128 KiB.")

        object.__setattr__(self, "definitions", frozen)
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))
        object.__setattr__(self, "mcp_schema_bytes", schema_bytes)
        object.__setattr__(self, "mcp_model_payload_bytes", payload_bytes)

    def resolve(self, name: str) -> ToolDefinition | None:
        return self._by_name.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    def mcp_definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(definition for definition in self.definitions if definition.source == "mcp")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _clone_json(value: Any) -> Any:
    return json.loads(_canonical_json_bytes(value))


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


def _fingerprint_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _validation_path(segments: Iterable[Any]) -> str:
    path = "$"
    for segment in segments:
        path += f"[{segment}]" if isinstance(segment, int) else f".{str(segment)[:128]}"
    return path[:1024]


def _normalized_public_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name).casefold()


def _truncate_description(description: str) -> str:
    if len(description) <= _MAX_DESCRIPTION_CHARS:
        return description
    keep = _MAX_DESCRIPTION_CHARS - len(_DESCRIPTION_TRUNCATION_MARKER)
    return description[:keep] + _DESCRIPTION_TRUNCATION_MARKER


def _builtin_risk(name: str) -> ToolRisk:
    if name in _TERMINAL_TOOLS:
        return "terminal"
    if name in _LOW_RISK_TOOLS:
        return "low-risk"
    if name in _CONFIRMATION_REQUIRED_TOOLS:
        return "confirmation-required"
    raise ToolCatalogError(f"Builtin tool {name!r} has no risk classification.")


def _builtin_definition(name: str) -> ToolDefinition:
    model = ARGS_MODELS[name]
    schema = _clone_json(model.model_json_schema())
    return ToolDefinition(
        name=name,
        description=MODEL_TOOL_DESCRIPTIONS[name],
        input_schema=_freeze_json(schema),
        risk=_builtin_risk(name),
        dry_run="skipped" if name in _BUILTIN_DRY_RUN_SKIPPED else "executes",
        source="builtin",
        target=None,
        _validator=model,
        _validator_fingerprint=None,
        _aliases=MappingProxyType(dict(ARG_ALIASES.get(name, {}))),
    )


@lru_cache(maxsize=1)
def builtin_tool_catalog() -> ToolCatalog:
    if set(MODEL_TOOL_DESCRIPTIONS) != set(ARGS_MODELS):
        raise ToolCatalogError("Builtin tool descriptions are incomplete.")
    return ToolCatalog(_builtin_definition(name) for name in ARGS_MODELS)


def _runtime_tool_definition(runtime_definition: Any) -> ToolDefinition:
    name = getattr(runtime_definition, "exposed_name", None)
    description = getattr(runtime_definition, "description", None)
    target = getattr(runtime_definition, "target", None)
    validator = getattr(runtime_definition, "input_validator", None)
    if not isinstance(name, str) or _PUBLIC_NAME_PATTERN.fullmatch(name) is None:
        raise ToolCatalogError("MCP tool has an invalid public name.")
    if not isinstance(description, str):
        raise ToolCatalogError(f"MCP tool {name!r} has an incomplete description contract.")
    if (
        target is None
        or not isinstance(getattr(target, "server_id", None), str)
        or not getattr(target, "server_id")
        or not isinstance(getattr(target, "remote_name", None), str)
        or not getattr(target, "remote_name")
    ):
        raise ToolCatalogError(f"MCP tool {name!r} has an incomplete target contract.")
    if not callable(getattr(validator, "iter_errors", None)) or not hasattr(validator, "schema"):
        raise ToolCatalogError(f"MCP tool {name!r} has an incomplete validator contract.")

    try:
        input_schema = _clone_json(getattr(runtime_definition, "input_schema"))
        input_bytes = _canonical_json_bytes(input_schema)
        validator_bytes = _canonical_json_bytes(getattr(validator, "schema"))
    except (AttributeError, RecursionError, TypeError, ValueError):
        raise ToolCatalogError(f"MCP tool {name!r} has an incomplete validator contract.") from None
    if not isinstance(input_schema, dict) or input_bytes != validator_bytes:
        raise ToolCatalogError(f"MCP tool {name!r} has a mismatched validator contract.")

    output_schema_value = getattr(runtime_definition, "output_schema", None)
    output_bytes = b""
    output_validator = getattr(getattr(target, "snapshot_contract", None), "output_validator", None)
    if output_schema_value is None:
        if output_validator is not None:
            raise ToolCatalogError(f"MCP tool {name!r} has a mismatched output contract.")
    else:
        try:
            output_schema = _clone_json(output_schema_value)
            output_bytes = _canonical_json_bytes(output_schema)
            output_validator_bytes = _canonical_json_bytes(getattr(output_validator, "schema"))
        except (AttributeError, RecursionError, TypeError, ValueError):
            raise ToolCatalogError(f"MCP tool {name!r} has an incomplete output contract.") from None
        if not isinstance(output_schema, dict) or output_bytes != output_validator_bytes:
            raise ToolCatalogError(f"MCP tool {name!r} has a mismatched output contract.")

    return ToolDefinition(
        name=name,
        description=_truncate_description(description),
        input_schema=_freeze_json(input_schema),
        risk="confirmation-required",
        dry_run="skipped",
        source="mcp",
        target=target,
        _validator=validator,
        _validator_fingerprint=hashlib.sha256(validator_bytes).hexdigest(),
        _aliases=MappingProxyType({}),
        _schema_bytes=len(input_bytes) + len(output_bytes),
    )


def build_tool_catalog(runtime_definitions: Iterable[Any] = ()) -> ToolCatalog:
    dynamic = tuple(runtime_definitions)
    if not dynamic:
        return builtin_tool_catalog()
    return ToolCatalog(
        (*builtin_tool_catalog().definitions, *(_runtime_tool_definition(item) for item in dynamic))
    )


DRY_RUN_SKIPPED_TOOLS = {
    definition.name
    for definition in builtin_tool_catalog().definitions
    if definition.dry_run == "skipped"
}


def list_tool_infos() -> list[ToolInfo]:
    catalog = builtin_tool_catalog()
    return [
        ToolInfo(
            name=name,
            category=catalog.resolve(name).risk,
            dry_run=catalog.resolve(name).dry_run,
            description=description,
        )
        for name, description in TOOL_DESCRIPTIONS.items()
    ]


def tool_category(tool_name: str) -> str:
    definition = builtin_tool_catalog().resolve(tool_name)
    return definition.risk if definition is not None else "unknown"


__all__ = [
    "DRY_RUN_SKIPPED_TOOLS",
    "MODEL_TOOL_DESCRIPTIONS",
    "TOOL_DESCRIPTIONS",
    "ToolArgumentError",
    "ToolCatalog",
    "ToolCatalogError",
    "ToolDefinition",
    "ToolInfo",
    "build_tool_catalog",
    "builtin_tool_catalog",
    "list_tool_infos",
    "tool_category",
]
