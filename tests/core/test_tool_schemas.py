from __future__ import annotations

from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from agent.core.actions import ARGS_MODELS
from agent.core.loop import SUPPORTED_TOOL_ACTIONS
from agent.core.tool_catalog import ToolArgumentError, ToolCatalogError, build_tool_catalog
from agent.core.tool_schemas import ACTION_DESCRIPTIONS, build_tool_schemas, native_tool_names
from agent.mcp_runtime import McpToolDefinition, McpToolTarget


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

def _mcp_definition(
    exposed_name: str = "mcp__local__echo",
    *,
    schema: dict | None = None,
    validator_schema: dict | None = None,
    description: str = "Echo a message.",
    validator: object | None = None,
) -> McpToolDefinition:
    public_schema = schema or {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    compiled_schema = validator_schema or {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    return McpToolDefinition(
        exposed_name=exposed_name,
        target=McpToolTarget(
            server_id="local",
            remote_name=exposed_name.rsplit("__", 1)[-1],
            snapshot_contract=SimpleNamespace(output_validator=None),
        ),
        description=description,
        input_schema=public_schema,
        output_schema=None,
        input_validator=validator or Draft202012Validator(compiled_schema),
    )


def test_dynamic_tool_schema_comes_from_immutable_catalog() -> None:
    runtime_schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    validator_schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
    runtime_definition = _mcp_definition(
        schema=runtime_schema,
        validator_schema=validator_schema,
    )
    catalog = build_tool_catalog((runtime_definition,))

    runtime_schema["properties"]["message"]["type"] = "integer"
    payload = build_tool_schemas(["mcp__local__echo"], tool_catalog=catalog)

    assert payload[0]["function"]["parameters"]["properties"]["message"]["type"] == "string"
    assert catalog.resolve("mcp__local__echo").validate_arguments({"message": "safe"}) == {
        "message": "safe"
    }

    runtime_definition.input_validator.schema["properties"]["message"]["type"] = "integer"
    with pytest.raises(ToolArgumentError, match="validator contract"):
        catalog.resolve("mcp__local__echo").validate_arguments({"message": "safe"})


def test_dynamic_description_is_marked_and_truncated_to_one_thousand_characters() -> None:
    catalog = build_tool_catalog((_mcp_definition(description="x" * 1500),))
    definition = catalog.resolve("mcp__local__echo")

    assert len(definition.description) == 1000
    assert definition.description.endswith("[truncated]")


@pytest.mark.parametrize(
    "definitions, expected",
    [
        (
            (
                _mcp_definition("mcp__local__echo"),
                _mcp_definition("mcp__local__echo"),
            ),
            "conflict",
        ),
        (
            (
                _mcp_definition("mcp__local__Echo"),
                _mcp_definition("mcp__local__echo"),
            ),
            "normalized",
        ),
    ],
)
def test_catalog_rejects_public_name_conflicts(definitions, expected: str) -> None:
    with pytest.raises(ToolCatalogError, match=expected):
        build_tool_catalog(definitions)


def test_catalog_rejects_more_than_sixty_four_mcp_tools() -> None:
    definitions = tuple(
        _mcp_definition(f"mcp__local__tool_{index}")
        for index in range(65)
    )

    with pytest.raises(ToolCatalogError, match="64"):
        build_tool_catalog(definitions)


def test_catalog_rejects_total_schema_budget() -> None:
    definitions = tuple(
        _mcp_definition(
            f"mcp__local__schema_{index}",
            schema={"type": "object", "description": "x" * (60 * 1024)},
            validator_schema={"type": "object", "description": "x" * (60 * 1024)},
        )
        for index in range(9)
    )

    with pytest.raises(ToolCatalogError, match="512 KiB"):
        build_tool_catalog(definitions)


def test_catalog_rejects_final_model_payload_budget() -> None:
    definitions = tuple(
        _mcp_definition(
            f"mcp__local__payload_{index}",
            schema={"type": "object", "description": "x" * (44 * 1024)},
            validator_schema={"type": "object", "description": "x" * (44 * 1024)},
        )
        for index in range(3)
    )

    with pytest.raises(ToolCatalogError, match="128 KiB"):
        build_tool_catalog(definitions)


def test_catalog_rejects_incomplete_runtime_validator_contract() -> None:
    with pytest.raises(ToolCatalogError, match="validator contract"):
        build_tool_catalog((_mcp_definition(validator=object()),))


def test_native_names_can_be_derived_from_explicit_catalog() -> None:
    catalog = build_tool_catalog((_mcp_definition(),))
    names = native_tool_names(web_search_enabled=False, tool_catalog=catalog)

    assert names[:2] == ["done", "ask_user"]
    assert "web_search" not in names
    assert "mcp__local__echo" in names
