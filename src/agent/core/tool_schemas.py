from __future__ import annotations

from collections.abc import Iterable

from agent.core.tool_catalog import (
    MODEL_TOOL_DESCRIPTIONS,
    ToolCatalog,
    builtin_tool_catalog,
)

ACTION_DESCRIPTIONS: dict[str, str] = dict(MODEL_TOOL_DESCRIPTIONS)
_TERMINAL_ACTIONS = ("done", "ask_user")


def native_tool_names(
    *,
    web_search_enabled: bool,
    tool_catalog: ToolCatalog | None = None,
) -> list[str]:
    catalog = tool_catalog or builtin_tool_catalog()
    names = [name for name in _TERMINAL_ACTIONS if catalog.resolve(name) is not None]
    for name in sorted(set(catalog.names()) - set(_TERMINAL_ACTIONS)):
        if name == "web_search" and not web_search_enabled:
            continue
        names.append(name)
    return names


def build_tool_schemas(
    action_names: Iterable[str],
    *,
    tool_catalog: ToolCatalog | None = None,
) -> list[dict]:
    catalog = tool_catalog or builtin_tool_catalog()
    schemas: list[dict] = []
    for name in action_names:
        definition = catalog.resolve(name)
        if definition is None:
            raise KeyError(name)
        schemas.append(definition.model_schema())
    return schemas
