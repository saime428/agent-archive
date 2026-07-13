from __future__ import annotations

from agent.core.actions import ARGS_MODELS
from agent.core.loop import SUPPORTED_TOOL_ACTIONS
from agent.core.tool_schemas import ACTION_DESCRIPTIONS, build_tool_schemas, native_tool_names


def test_every_action_has_a_description() -> None:
    assert set(ACTION_DESCRIPTIONS) == set(ARGS_MODELS)
    assert all(desc.strip() for desc in ACTION_DESCRIPTIONS.values())


def test_native_tool_names_always_include_terminals() -> None:
    names = native_tool_names(web_search_enabled=True)

    assert names[0] == "done"
    assert names[1] == "ask_user"
    assert "read_file" in names
    assert "web_search" in names


def test_native_tool_names_hide_web_search_when_disabled() -> None:
    names = native_tool_names(web_search_enabled=False)

    assert "web_search" not in names
    assert "read_file" in names


def test_native_tool_names_match_loop_execution_actions() -> None:
    assert set(native_tool_names(web_search_enabled=True)) == SUPPORTED_TOOL_ACTIONS | {"done", "ask_user"}


def test_build_tool_schemas_shape() -> None:
    schemas = build_tool_schemas(["done", "read_file"])

    assert [schema["function"]["name"] for schema in schemas] == ["done", "read_file"]
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["description"].strip()
        parameters = schema["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
    read_file_params = schemas[1]["function"]["parameters"]
    assert "path" in read_file_params["properties"]
