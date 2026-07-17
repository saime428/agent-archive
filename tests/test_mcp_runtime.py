from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.mcp_runtime import (
    McpCallResult,
    McpRuntimeError,
    McpServerConfig,
    McpToolDefinition,
    McpToolTarget,
    build_mcp_tool_name,
    load_mcp_server_configs,
)


def _toml_string(value: str | Path) -> str:
    return json.dumps(str(value))


def _write_config(home: Path, content: str) -> Path:
    path = home / ".agent" / "mcp.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_executable(directory: Path, name: str = "trusted-tool") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    path = directory / f"{name}{suffix}"
    path.write_text("fixture\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o755)
    return path


def _path_environment(*directories: Path, pathext: str = ".CMD;.EXE;.BAT;.PS1;.COM") -> dict[str, str]:
    return {"PATH": os.pathsep.join(str(path) for path in directories), "PATHEXT": pathext}


def _safe_environment() -> dict[str, str]:
    return _path_environment(Path(sys.executable).resolve().parent, pathext=".EXE;.COM")


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (NotImplementedError, OSError) as exc:
        if os.name == "nt":
            junction = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=False,
            )
            if junction.returncode == 0:
                return
        pytest.skip(f"directory links are unavailable: {exc}")


def _extended_windows_path(path: Path) -> Path:
    value = str(path.resolve())
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def _valid_server(command: str | Path | None = None) -> str:
    return (
        "[servers.local]\n"
        f"command = {_toml_string(command or Path(sys.executable).resolve())}\n"
        'args = ["{workspace}", "prefix-{workspace}"]\n'
        'pass_env = ["MCP_TOKEN"]\n'
    )


def test_mcp_value_objects_expose_only_runtime_contract() -> None:
    contract = object()
    validator = object()
    target = McpToolTarget(server_id="local", remote_name="echo", snapshot_contract=contract)
    definition = McpToolDefinition(
        exposed_name="mcp__local__echo",
        target=target,
        description="Echo text.",
        input_schema={"type": "object"},
        output_schema=None,
        input_validator=validator,
    )
    result = McpCallResult(
        status="ok",
        summary="Called echo.",
        data={"content": []},
        diagnostic_details=None,
        redaction_replacements=2,
    )
    error = McpRuntimeError(stage="config", server_id="local", message="invalid")

    assert definition.target is target
    assert target.snapshot_contract is contract
    assert result.redaction_replacements == 2
    assert error.stage == "config"
    assert error.server_id == "local"
    assert error.message == "invalid"
    assert "local" in str(error)


def test_missing_user_config_returns_empty_and_ignores_project_config(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(workspace, _valid_server())

    assert load_mcp_server_configs(workspace, home=home, environ={}) == ()


def test_loads_valid_user_config_and_expands_only_whole_workspace_token(tmp_path) -> None:
    workspace = (tmp_path / "workspace").resolve()
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(home, _valid_server() + 'cwd = "workspace"\n')

    configs = load_mcp_server_configs(workspace, home=home, environ=_safe_environment())

    assert len(configs) == 1
    config = configs[0]
    assert isinstance(config, McpServerConfig)
    assert config.server_id == "local"
    assert config.command == Path(sys.executable).resolve()
    assert config.args == (str(workspace), "prefix-{workspace}")
    assert config.pass_env == ("MCP_TOKEN",)
    assert config.cwd == workspace


def test_default_server_cwd_is_user_agent_directory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    path = _write_config(
        home,
        "[servers.local]\n"
        f"command = {_toml_string(Path(sys.executable).resolve())}\n",
    )
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    config = load_mcp_server_configs(workspace, home=home, environ=_safe_environment())[0]

    assert config.cwd == path.parent.resolve()
    assert config.args == ()
    assert config.pass_env == ()


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("[\n", "parse"),
        ("other = true\n", "top-level"),
        ("servers = []\n", "'servers'"),
        ('servers = { local = "not-a-table" }\n', "TOML table"),
        ('[servers.""]\ncommand = "tool"\n', "Server ID"),
        ('[servers."bad id"]\ncommand = "tool"\nargs = []\npass_env = []\n', "Server ID"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = []\nunknown = true\n', "server field"),
        ("[servers.local]\nargs = []\npass_env = []\n", "'command'"),
        ('[servers.local]\ncommand = ""\nargs = []\npass_env = []\n', "'command'"),
        ("[servers.local]\ncommand = 1\nargs = []\npass_env = []\n", "'command'"),
        ('[servers.local]\ncommand = "\\u0000"\n', "'command'"),
        ('[servers.local]\ncommand = "tool"\nargs = "x"\npass_env = []\n', "'args'"),
        ('[servers.local]\ncommand = "tool"\nargs = [1]\npass_env = []\n', "'args'"),
        ('[servers.local]\ncommand = "tool"\nargs = ["\\u0000"]\n', "'args'"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = "TOKEN"\n', "'pass_env'"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = ["bad=name"]\n', "Invalid pass_env"),
        (
            '[servers.local]\ncommand = "tool"\nargs = []\npass_env = ["TOKEN", "TOKEN"]\n',
            "Duplicate pass_env",
        ),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = ["PATH"]\n', "reserved"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = ["PATHEXT"]\n', "reserved"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = []\ncwd = "other"\n', "'cwd'"),
        ('[servers.local]\ncommand = "tool"\nargs = []\npass_env = []\ncwd = 1\n', "'cwd'"),
    ],
)
def test_rejects_invalid_mcp_config(tmp_path, content: str, expected_error: str) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    content = content.replace('command = "tool"', f"command = {_toml_string(Path(sys.executable).resolve())}")
    _write_config(home, content)

    with pytest.raises(McpRuntimeError, match=expected_error) as exc_info:
        load_mcp_server_configs(workspace, home=home, environ={})

    assert exc_info.value.stage == "config"


def test_rejects_invalid_utf8_as_config_error(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    path = _write_config(home, _valid_server())
    path.write_bytes(b"\xff")

    with pytest.raises(McpRuntimeError) as exc_info:
        load_mcp_server_configs(workspace, home=home, environ={})

    assert exc_info.value.stage == "config"


@pytest.mark.skipif(os.name != "nt", reason="Windows environment names are case-insensitive")
@pytest.mark.parametrize("reserved", ["Path", "path", "Pathext", "pathext"])
def test_windows_rejects_case_variants_of_reserved_path_environment(tmp_path, reserved: str) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(
        home,
        _valid_server().replace('pass_env = ["MCP_TOKEN"]', f'pass_env = ["{reserved}"]'),
    )

    with pytest.raises(McpRuntimeError, match="reserved"):
        load_mcp_server_configs(workspace, home=home, environ={})


def test_rejects_more_than_eight_servers(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    servers = "\n".join(
        f'[servers.s{index}]\ncommand = {_toml_string(Path(sys.executable).resolve())}\nargs = []\npass_env = []'
        for index in range(9)
    )
    _write_config(home, servers)

    with pytest.raises(McpRuntimeError, match="8"):
        load_mcp_server_configs(workspace, home=home, environ={})


def test_accepts_exactly_eight_servers(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    servers = "\n".join(
        f'[servers.s{index}]\ncommand = {_toml_string(Path(sys.executable).resolve())}' for index in range(8)
    )
    _write_config(home, servers)

    configs = load_mcp_server_configs(workspace, home=home, environ=_safe_environment())

    assert len(configs) == 8


@pytest.mark.parametrize(
    "command",
    ["./tool", "subdir/tool", ".\\tool", "subdir\\tool", "C:tool", "\\tool"],
)
def test_rejects_relative_command_paths(tmp_path, command: str) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(home, _valid_server(command))

    with pytest.raises(McpRuntimeError, match="command paths"):
        load_mcp_server_configs(workspace, home=home, environ={})


def test_rejects_missing_or_directory_absolute_command(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    directory = tmp_path / "directory"
    workspace.mkdir()
    directory.mkdir()

    for command in (tmp_path / "missing.exe", directory):
        _write_config(home, _valid_server(command))
        with pytest.raises(McpRuntimeError, match="file"):
            load_mcp_server_configs(workspace, home=home, environ={})


def test_bare_command_uses_only_canonical_non_workspace_path_entries(tmp_path) -> None:
    workspace = (tmp_path / "workspace").resolve()
    home = tmp_path / "home"
    relative = Path("relative-bin")
    workspace.mkdir()
    shadow = _make_executable(workspace / "node_modules" / ".bin")
    trusted = _make_executable(tmp_path / "trusted")
    _write_config(home, _valid_server("trusted-tool"))
    environment = _path_environment(relative, shadow.parent, trusted.parent, trusted.parent)
    environment["PATH"] = os.pathsep.join(("", environment["PATH"]))

    config = load_mcp_server_configs(workspace, home=home, environ=environment)[0]

    assert config.command == trusted.resolve()
    path_entries = tuple(Path(value) for value in config.subprocess_path.split(os.pathsep) if value)
    assert path_entries == (trusted.parent.resolve(),)
    assert all(path.is_absolute() for path in path_entries)
    assert workspace not in path_entries
    if os.name == "nt":
        assert config.subprocess_pathext == ".EXE;.COM"


def test_bare_command_fails_when_only_workspace_shadow_exists(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    shadow = _make_executable(workspace / ".venv" / "Scripts")
    _write_config(home, _valid_server("trusted-tool"))

    with pytest.raises(McpRuntimeError, match="not found"):
        load_mcp_server_configs(workspace, home=home, environ=_path_environment(shadow.parent))


def test_bare_command_skips_directory_candidate_and_uses_next_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    first = tmp_path / "first"
    trusted = _make_executable(tmp_path / "trusted")
    workspace.mkdir()
    first.mkdir()
    (first / trusted.name).mkdir()
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(first, trusted.parent),
    )[0]

    assert config.command == trusted.resolve()


def test_path_directory_link_into_workspace_is_filtered(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    shadow = _make_executable(workspace / "shadow-bin")
    trusted = _make_executable(tmp_path / "trusted")
    alias = tmp_path / "workspace-bin-alias"
    _make_directory_link(alias, shadow.parent)
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(alias, trusted.parent),
    )[0]

    assert config.command == trusted.resolve()
    assert str(alias) not in config.subprocess_path
    assert str(shadow.parent.resolve()) not in config.subprocess_path


def test_path_directory_with_separator_is_not_serialized_back_as_two_entries(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    separator_target = tmp_path / f"trusted{os.pathsep}relative-bin"
    _make_executable(separator_target)
    alias = tmp_path / "separator-alias"
    _make_directory_link(alias, separator_target)
    trusted = _make_executable(tmp_path / "trusted")
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(alias, trusted.parent),
    )[0]

    assert config.command == trusted.resolve()
    assert config.subprocess_path == str(trusted.parent.resolve())


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path syntax")
def test_extended_workspace_path_entry_is_filtered(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    shadow = _make_executable(workspace / "shadow-bin")
    trusted = _make_executable(tmp_path / "trusted")
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(_extended_windows_path(shadow.parent), trusted.parent),
    )[0]

    assert config.command == trusted.resolve()
    assert str(shadow.parent.resolve()) not in config.subprocess_path


def test_executable_link_into_workspace_is_skipped_for_next_candidate(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    unsafe = tmp_path / "unsafe"
    workspace.mkdir()
    unsafe.mkdir()
    shadow = _make_executable(workspace / "tools")
    trusted = _make_executable(tmp_path / "trusted")
    try:
        (unsafe / shadow.name).symlink_to(shadow)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(unsafe, trusted.parent),
    )[0]

    assert config.command == trusted.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows native executable contract")
def test_executable_name_linked_to_script_is_skipped(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    unsafe = tmp_path / "unsafe"
    workspace.mkdir()
    unsafe.mkdir()
    script = tmp_path / "server.cmd"
    script.write_text("@exit /b 0\n", encoding="utf-8")
    try:
        (unsafe / "trusted-tool.exe").symlink_to(script)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    trusted = _make_executable(tmp_path / "trusted")
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(unsafe, trusted.parent),
    )[0]

    assert config.command == trusted.resolve()


def test_explicit_absolute_workspace_command_is_accepted(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    explicit = _make_executable(workspace / "tools")
    _write_config(home, _valid_server(explicit.resolve()))

    config = load_mcp_server_configs(workspace, home=home, environ=_safe_environment())[0]

    assert config.command == explicit.resolve()


def test_normalizes_and_filters_pathext_snapshot(tmp_path) -> None:
    if os.name != "nt":
        pytest.skip("PATHEXT is Windows-specific")
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    trusted = _make_executable(tmp_path / "trusted")
    workspace.mkdir()
    _write_config(home, _valid_server("trusted-tool"))

    config = load_mcp_server_configs(
        workspace,
        home=home,
        environ=_path_environment(trusted.parent, pathext=".cmd;CMD;.EXE;.py;.BAT;.PS1;.com;.cmd"),
    )[0]

    assert config.subprocess_pathext == ".EXE;.COM"


@pytest.mark.skipif(os.name != "nt", reason="Windows script launch semantics")
@pytest.mark.parametrize("suffix", [".cmd", ".bat", ".ps1"])
def test_windows_rejects_script_commands_even_when_absolute(tmp_path, suffix: str) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    script = tmp_path / f"server{suffix}"
    script.write_text("exit 0\n", encoding="utf-8")
    _write_config(home, _valid_server(script.resolve()))

    with pytest.raises(McpRuntimeError, match="native executable"):
        load_mcp_server_configs(workspace, home=home, environ={})


@pytest.mark.skipif(os.name != "nt", reason="Windows script launch semantics")
def test_windows_does_not_resolve_bare_batch_command(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    scripts = tmp_path / "scripts"
    workspace.mkdir()
    scripts.mkdir()
    (scripts / "server.cmd").write_text("@exit /b 0\n", encoding="utf-8")
    _write_config(home, _valid_server("server"))

    with pytest.raises(McpRuntimeError, match="not found"):
        load_mcp_server_configs(
            workspace,
            home=home,
            environ=_path_environment(scripts, pathext=".CMD;.BAT;.PS1"),
        )


def test_rejects_enabled_server_when_sanitized_path_is_empty(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(home, _valid_server())

    with pytest.raises(McpRuntimeError, match="Sanitized PATH"):
        load_mcp_server_configs(workspace, home=home, environ={})


def test_rejects_user_config_that_resolves_inside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_config(workspace, _valid_server())

    with pytest.raises(McpRuntimeError, match="workspace"):
        load_mcp_server_configs(workspace, home=workspace, environ={})


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path syntax")
def test_rejects_user_config_under_extended_workspace_path(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_config(workspace, _valid_server())

    with pytest.raises(McpRuntimeError, match="workspace"):
        load_mcp_server_configs(workspace, home=_extended_windows_path(workspace), environ={})


@pytest.mark.parametrize("link_parent", [False, True])
def test_rejects_user_config_symlink_or_parent_symlink_into_workspace(tmp_path, link_parent: bool) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    target_dir = workspace / "config-source"
    workspace.mkdir()
    target = _write_config(target_dir.parent, _valid_server())
    agent_dir = home / ".agent"
    home.mkdir()

    try:
        if link_parent:
            _make_directory_link(agent_dir, target.parent)
        else:
            agent_dir.mkdir()
            (agent_dir / "mcp.toml").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(McpRuntimeError, match="workspace"):
        load_mcp_server_configs(workspace, home=home, environ={})


def test_user_agent_directory_link_outside_workspace_is_allowed(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    external_agent = tmp_path / "external-agent"
    workspace.mkdir()
    home.mkdir()
    external_agent.mkdir()
    (external_agent / "mcp.toml").write_text(_valid_server(), encoding="utf-8")
    _make_directory_link(home / ".agent", external_agent)

    config = load_mcp_server_configs(workspace, home=home, environ=_safe_environment())[0]

    assert config.cwd == external_agent.resolve()


def test_default_environment_uses_import_time_path_snapshot(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    injected = tmp_path / "late-path"
    workspace.mkdir()
    injected.mkdir()
    _write_config(home, _valid_server())
    monkeypatch.setenv("PATH", str(injected))

    config = load_mcp_server_configs(workspace, home=home)[0]
    path_entries = config.subprocess_path.split(os.pathsep)

    assert str(injected.resolve()) not in path_entries


def test_build_mcp_tool_name_normalizes_and_hashes_stably() -> None:
    assert build_mcp_tool_name("github", "search issues/v2") == "mcp__github__search_issues_v2"
    assert build_mcp_tool_name("github", "a.b") == build_mcp_tool_name("github", "a/b")

    normalized_full = "mcp__github__" + "x" * 100
    expected = normalized_full[:55] + "_" + hashlib.sha256(normalized_full.encode()).hexdigest()[:8]
    exposed = build_mcp_tool_name("github", "x" * 100)

    assert exposed == expected
    assert len(exposed) == 64
