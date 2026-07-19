from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest

import agent.mcp_runtime as mcp_runtime_module
from agent.mcp_runtime import (
    McpCallResult,
    McpRuntimeError,
    McpServerConfig,
    McpStdioRuntime,
    McpToolDefinition,
    McpToolTarget,
    build_mcp_tool_name,
    load_mcp_server_configs,
)


_STDIO_FIXTURE = (Path(__file__).parent / "fixtures" / "mcp_stdio_server.py").resolve()


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


def _write_runtime_config(
    home: Path,
    *,
    mode: str = "default",
    schema: str = "valid",
    output_schema: str = "none",
    pass_env: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> None:
    args = [
        str(_STDIO_FIXTURE),
        "--mode",
        mode,
        "--schema",
        schema,
        "--output-schema",
        output_schema,
        *extra_args,
    ]
    _write_config(
        home,
        "[servers.local]\n"
        f"command = {_toml_string(Path(sys.executable).resolve())}\n"
        f"args = {json.dumps(args)}\n"
        f"pass_env = {json.dumps(pass_env)}\n",
    )


def _runtime(
    tmp_path: Path,
    *,
    mode: str = "default",
    schema: str = "valid",
    output_schema: str = "none",
    pass_env: tuple[str, ...] = (),
    environ: dict[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
) -> McpStdioRuntime:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_runtime_config(
        home,
        mode=mode,
        schema=schema,
        output_schema=output_schema,
        pass_env=pass_env,
        extra_args=extra_args,
    )
    return McpStdioRuntime(
        workspace,
        home=home,
        environ={**_safe_environment(), **(environ or {})},
    )


def _wait_for_file(path: Path, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _assert_runtime_stopped(runtime: McpStdioRuntime) -> None:
    assert runtime._thread is None or not runtime._thread.is_alive()


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return

    import signal

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _wait_for_pid_exit(pid: int, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} did not exit")



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


def test_stdio_runtime_without_config_stays_lazy_and_close_is_idempotent(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = McpStdioRuntime(workspace, home=tmp_path / "home", environ=_safe_environment())

    assert runtime._thread is None
    assert runtime.discover_tools() == ()
    assert runtime._thread is None

    runtime.close()
    runtime.close()
    _assert_runtime_stopped(runtime)


@pytest.mark.parametrize(
    ("mode", "expected_names"),
    [
        ("default", ("mcp__local__echo",)),
        ("pagination", ("mcp__local__echo", "mcp__local__upper")),
    ],
)
def test_stdio_runtime_discovers_real_fixture_and_precompiles_validator(
    tmp_path,
    mode: str,
    expected_names: tuple[str, ...],
) -> None:
    runtime = _runtime(tmp_path, mode=mode)
    try:
        definitions = runtime.discover_tools()

        assert tuple(definition.exposed_name for definition in definitions) == expected_names
        assert all(definition.target.server_id == "local" for definition in definitions)
        assert all(definition.input_schema["type"] == "object" for definition in definitions)
        assert all(definition.input_validator.is_valid({"message": "ok"}) for definition in definitions)
        assert all(not definition.input_validator.is_valid({"message": 1}) for definition in definitions)
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


@pytest.mark.parametrize(
    ("mode", "schema"),
    [
        ("no-tools", "valid"),
        ("repeat-cursor", "valid"),
        ("unique-cursor", "valid"),
        ("large-page", "valid"),
        ("default", "invalid-root"),
        ("default", "invalid-dialect"),
        ("default", "external-ref"),
        ("default", "external-dynamic-ref"),
        ("default", "missing-ref"),
        ("default", "missing-dynamic-ref"),
        ("default", "regex"),
        ("default", "oversize"),
    ],
)
def test_stdio_runtime_rejects_unsafe_discovery_atomically(
    tmp_path,
    mode: str,
    schema: str,
) -> None:
    runtime = _runtime(tmp_path, mode=mode, schema=schema)
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        assert exc_info.value.server_id == "local"
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_precompiles_local_input_and_output_refs_from_frozen_copies(
    tmp_path,
) -> None:
    runtime = _runtime(
        tmp_path,
        schema="valid-local-ref",
        output_schema="valid-local-ref",
    )
    try:
        definition = runtime.discover_tools()[0]
        output_validator = definition.target.snapshot_contract.output_validator

        assert definition.input_validator.is_valid({"message": "ok"})
        assert output_validator.is_valid({"message": "ok"})
        definition.input_schema["$defs"]["message"]["type"] = "integer"
        assert definition.input_validator.is_valid({"message": "still-valid"})
        assert not definition.input_validator.is_valid({"message": 1})
    finally:
        runtime.close()


def test_stdio_runtime_treats_schema_keyword_names_as_plain_property_names(tmp_path) -> None:
    runtime = _runtime(tmp_path, schema="keyword-property-names")
    try:
        definition = runtime.discover_tools()[0]
        assert definition.input_validator.is_valid(
            {"$ref": "value", "$schema": "value", "pattern": "value"}
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "output_schema",
    [
        "invalid-root",
        "invalid-dialect",
        "external-ref",
        "external-dynamic-ref",
        "missing-ref",
        "missing-dynamic-ref",
        "regex",
        "oversize",
    ],
)
def test_stdio_runtime_rejects_unsafe_output_schema(
    tmp_path,
    output_schema: str,
) -> None:
    runtime = _runtime(tmp_path, output_schema=output_schema)
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        assert exc_info.value.server_id == "local"
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_enforces_combined_input_output_schema_budget(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        schema="half-large",
        output_schema="half-large",
    )
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_rejects_secret_schema_without_logging_it(tmp_path, caplog) -> None:
    secret = "schema-secret-23c9d7"
    caplog.set_level(logging.DEBUG)
    runtime = _runtime(
        tmp_path,
        schema="env-secret",
        pass_env=("MCP_FIXTURE_SCHEMA_SECRET",),
        environ={"MCP_FIXTURE_SCHEMA_SECRET": secret},
    )
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert secret not in str(exc_info.value)
        assert secret not in caplog.text
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_leaves_duplicate_remote_names_for_catalog_validation(tmp_path) -> None:
    runtime = _runtime(tmp_path, mode="duplicate-tools")
    try:
        definitions = runtime.discover_tools()

        assert len(definitions) == 2
        assert tuple(definition.target.remote_name for definition in definitions) == ("echo", "echo")
        assert tuple(definition.exposed_name for definition in definitions) == (
            "mcp__local__echo",
            "mcp__local__echo",
        )
    finally:
        runtime.close()



def test_stdio_runtime_redacts_pass_env_from_description(tmp_path) -> None:
    secret = "description-secret-23c9d7"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_FIXTURE_DESCRIPTION",),
        environ={"MCP_FIXTURE_DESCRIPTION": secret},
    )
    try:
        definition = runtime.discover_tools()[0]

        assert definition.description == "[REDACTED]"
        assert secret not in definition.description
    finally:
        runtime.close()


def test_stdio_runtime_does_not_inherit_undeclared_environment_values(
    tmp_path,
    monkeypatch,
) -> None:
    secret = "undeclared-secret-23c9d7"
    monkeypatch.setenv("MCP_FIXTURE_UNDECLARED", secret)
    runtime = _runtime(
        tmp_path,
        environ={"MCP_FIXTURE_UNDECLARED": secret},
        extra_args=("--description-env", "MCP_FIXTURE_UNDECLARED"),
    )
    try:
        definition = runtime.discover_tools()[0]

        assert definition.description == "<missing>"
        assert secret not in definition.description
    finally:
        runtime.close()


def test_stdio_runtime_overrides_sdk_path_with_sanitized_value(tmp_path) -> None:
    expected_path = str(Path(sys.executable).resolve().parent)
    runtime = _runtime(
        tmp_path,
        extra_args=("--description-env", "PATH"),
    )
    try:
        definition = runtime.discover_tools()[0]

        assert definition.description == expected_path
    finally:
        runtime.close()


def test_stdio_runtime_preserves_sdk_safe_default_environment(tmp_path) -> None:
    variable = "SYSTEMROOT" if os.name == "nt" else "HOME"
    expected = os.environ.get(variable)
    if expected is None:
        pytest.skip(f"{variable} is unavailable")

    runtime = _runtime(
        tmp_path,
        extra_args=("--description-env", variable),
    )
    try:
        definition = runtime.discover_tools()[0]

        assert definition.description == expected
    finally:
        runtime.close()



def test_stdio_runtime_rejects_secret_tool_name_without_logging_it(tmp_path, caplog) -> None:
    secret = "secret_tool_name_23c9d7"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_FIXTURE_TOOL_NAME",),
        environ={"MCP_FIXTURE_TOOL_NAME": secret},
    )
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        assert secret not in str(exc_info.value)
        assert secret not in caplog.text
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_checks_missing_pass_env_before_starting_process(tmp_path) -> None:
    start_file = tmp_path / "started.txt"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_MISSING_TOKEN",),
        extra_args=("--start-file", str(start_file)),
    )
    try:
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "initialize"
        assert "MCP_MISSING_TOKEN" in str(exc_info.value)
        assert not start_file.exists()
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_refreshes_on_next_discovery_after_list_changed(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="list-changed",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        first = runtime.discover_tools()
        assert tuple(definition.target.remote_name for definition in first) == ("echo",)

        deadline = time.monotonic() + 2.0
        refreshed = first
        while time.monotonic() < deadline:
            refreshed = runtime.discover_tools()
            if any(definition.target.remote_name == "refreshed" for definition in refreshed):
                break
            time.sleep(0.01)

        assert tuple(definition.target.remote_name for definition in refreshed) == ("echo", "refreshed")
    finally:
        runtime.close()


def test_stdio_runtime_first_discovery_is_single_flight(tmp_path) -> None:
    start_file = tmp_path / "started.txt"
    runtime = _runtime(
        tmp_path,
        mode="init-delay",
        extra_args=("--delay", "0.1", "--start-file", str(start_file)),
    )
    barrier = Barrier(3)

    def discover() -> tuple[McpToolDefinition, ...]:
        barrier.wait(timeout=2)
        return runtime.discover_tools()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(discover) for _ in range(2)]
            barrier.wait(timeout=2)
            results = [future.result(timeout=3) for future in futures]

        assert all(tuple(tool.exposed_name for tool in result) == ("mcp__local__echo",) for result in results)
        assert len(start_file.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_close_wins_race_with_initial_discovery(tmp_path) -> None:
    start_file = tmp_path / "started.txt"
    runtime = _runtime(
        tmp_path,
        mode="init-delay",
        extra_args=("--delay", "2", "--start-file", str(start_file)),
    )
    barrier = Barrier(3)

    def discover() -> Exception | None:
        barrier.wait(timeout=2)
        try:
            runtime.discover_tools()
        except Exception as exc:
            return exc
        return None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(discover) for _ in range(2)]
            barrier.wait(timeout=2)
            _wait_for_file(start_file)
            runtime.close()
            results = [future.result(timeout=3) for future in futures]

        assert all(isinstance(result, McpRuntimeError) for result in results)
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_malformed_stdout_is_fail_closed_secret_safe_and_restores_filters(
    tmp_path,
    caplog,
) -> None:
    secret = "stdout-secret-23c9d7"
    caplog.set_level(logging.DEBUG)
    root = logging.getLogger()
    stdio_logger = logging.getLogger("mcp.client.stdio")
    original_root_filters = tuple(root.filters)
    original_stdio_filters = tuple(stdio_logger.filters)
    runtime = _runtime(
        tmp_path,
        mode="malformed-stdout",
        pass_env=("MCP_FIXTURE_NOISE",),
        environ={"MCP_FIXTURE_NOISE": secret},
    )

    try:
        with pytest.raises(McpRuntimeError):
            runtime.discover_tools()
    finally:
        runtime.close()

    assert secret not in caplog.text
    assert all(secret not in record.getMessage() for record in caplog.records)
    assert tuple(root.filters) == original_root_filters
    assert tuple(stdio_logger.filters) == original_stdio_filters
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_stderr_flood_does_not_block_discovery(tmp_path) -> None:
    runtime = _runtime(tmp_path, mode="stderr-flood")
    try:
        definitions = runtime.discover_tools()
        assert tuple(definition.target.remote_name for definition in definitions) == ("echo",)
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


@pytest.mark.parametrize("mode", ["init-delay", "crash"])
def test_stdio_runtime_initialization_failure_is_sticky_and_does_not_retry(
    tmp_path,
    monkeypatch,
    mode: str,
) -> None:
    start_file = tmp_path / "started.txt"
    extra_args = ("--start-file", str(start_file))
    if mode == "init-delay":
        extra_args += ("--delay", "5")
        monkeypatch.setattr(mcp_runtime_module, "_DISCOVERY_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(mcp_runtime_module, "_CLOSE_TIMEOUT_SECONDS", 3.0)
    runtime = _runtime(tmp_path, mode=mode, extra_args=extra_args)
    try:
        with pytest.raises(McpRuntimeError) as first_error:
            runtime.discover_tools()
        with pytest.raises(McpRuntimeError) as second_error:
            runtime.discover_tools()

        assert first_error.value.stage in {"initialize", "discovery"}
        assert second_error.value.stage == first_error.value.stage
        assert len(start_file.read_text(encoding="utf-8").splitlines()) == 1
        _assert_runtime_stopped(runtime)
    finally:
        runtime.close()


def test_stdio_runtime_unsafe_refresh_keeps_previous_snapshot_and_session(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="list-changed-unsafe",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        first = runtime.discover_tools()
        deadline = time.monotonic() + 2
        refresh_error: McpRuntimeError | None = None
        while time.monotonic() < deadline:
            try:
                runtime.discover_tools()
            except McpRuntimeError as exc:
                refresh_error = exc
                break
            time.sleep(0.01)

        assert refresh_error is not None
        assert refresh_error.stage == "discovery"
        assert runtime._snapshot is first
        assert runtime._state == "ready"
        assert runtime._thread is not None and runtime._thread.is_alive()
        with pytest.raises(McpRuntimeError):
            runtime.discover_tools()
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_refresh_transport_failure_closes_runtime(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="list-changed-crash",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        runtime.discover_tools()
        deadline = time.monotonic() + 2
        refresh_error: McpRuntimeError | None = None
        while time.monotonic() < deadline:
            try:
                runtime.discover_tools()
            except McpRuntimeError as exc:
                refresh_error = exc
                break
            time.sleep(0.01)

        assert refresh_error is not None
        assert refresh_error.stage == "discovery"
        assert runtime._state == "failed"
        _assert_runtime_stopped(runtime)
        with pytest.raises(McpRuntimeError):
            runtime.discover_tools()
    finally:
        runtime.close()


def test_stdio_runtime_idle_server_exit_invalidates_ready_snapshot(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="idle-crash",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        assert runtime.discover_tools()
        assert runtime._loop_finished.wait(timeout=2)

        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_keyboard_interrupt_during_refresh_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = _runtime(
        tmp_path,
        mode="list-changed",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        runtime.discover_tools()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if runtime._dirty_generation.get("local", 0):
                break
            time.sleep(0.01)
        else:
            raise AssertionError("fixture did not mark the tool list dirty")

        def interrupt_refresh(server_ids, *, initial: bool):
            assert tuple(server_ids) == ("local",)
            assert not initial
            raise KeyboardInterrupt

        monkeypatch.setattr(runtime, "_dispatch_discovery", interrupt_refresh)
        with pytest.raises(KeyboardInterrupt):
            runtime.discover_tools()

        assert runtime._state == "failed"
        assert not runtime._refreshing
        _assert_runtime_stopped(runtime)
        with pytest.raises(McpRuntimeError):
            runtime.discover_tools()
    finally:
        runtime.close()


def test_stdio_runtime_invalid_notification_is_secret_safe_without_hiding_app_logs(
    tmp_path,
    monkeypatch,
    caplog,
    capsys,
) -> None:
    secret = "notification-secret-23c9d7"
    caplog.set_level(logging.DEBUG)
    loggers = [
        logging.getLogger(),
        logging.getLogger("mcp.client.stdio"),
        logging.getLogger("client.stdio.win32"),
    ]
    original_filters = [tuple(logger.filters) for logger in loggers]
    runtime = _runtime(
        tmp_path,
        mode="invalid-notification",
        pass_env=("MCP_FIXTURE_NOISE",),
        environ={"MCP_FIXTURE_NOISE": secret},
        extra_args=("--notify-delay", "0.03"),
    )
    original_list_tools = runtime._list_tools

    async def list_tools_with_app_log(session, start):
        logging.getLogger("agent.mcp-runtime-test").warning("owner-app-log-visible")
        return await original_list_tools(session, start)

    monkeypatch.setattr(runtime, "_list_tools", list_tools_with_app_log)
    try:
        first = runtime.discover_tools()
        logging.getLogger("agent.mcp-runtime-test").warning("other-thread-log-visible")
        time.sleep(0.15)
        assert runtime.discover_tools() is first
    finally:
        runtime.close()

    captured = capsys.readouterr()
    assert secret not in caplog.text
    assert secret not in captured.out
    assert secret not in captured.err
    assert "owner-app-log-visible" in caplog.text
    assert "other-thread-log-visible" in caplog.text
    assert [tuple(logger.filters) for logger in loggers] == original_filters
    _assert_runtime_stopped(runtime)


@pytest.mark.skipif(os.name != "nt", reason="SDK process-tree guarantee is Windows-only")
def test_stdio_runtime_close_removes_fixture_process_tree(tmp_path) -> None:
    child_file = tmp_path / "child.pid"
    runtime = _runtime(
        tmp_path,
        mode="child-process",
        extra_args=("--child-file", str(child_file)),
    )
    child_pid: int | None = None
    try:
        assert runtime.discover_tools()
        _wait_for_file(child_file)
        child_pid = int(child_file.read_text(encoding="ascii").strip())
        assert _pid_exists(child_pid)

        runtime.close()
        _wait_for_pid_exit(child_pid)
    finally:
        runtime.close()
        if child_pid is not None and _pid_exists(child_pid):
            _terminate_pid(child_pid)
    _assert_runtime_stopped(runtime)



def test_stdio_runtime_close_before_loop_ready_prevents_late_owner_start(
    tmp_path,
    monkeypatch,
) -> None:
    start_file = tmp_path / "started.txt"
    runtime = _runtime(
        tmp_path,
        extra_args=("--start-file", str(start_file)),
    )
    entered = Event()
    release = Event()
    original_loop_main = runtime._loop_main

    async def delayed_loop_main(starts) -> None:
        entered.set()
        if not release.wait(timeout=1):
            raise AssertionError("test did not release the MCP loop")
        await original_loop_main(starts)

    monkeypatch.setattr(mcp_runtime_module, "_CLOSE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(mcp_runtime_module, "_DISCOVERY_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(runtime, "_loop_main", delayed_loop_main)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.discover_tools)
        try:
            assert entered.wait(timeout=1)
            with pytest.raises(McpRuntimeError):
                runtime.close()
        finally:
            release.set()
            assert runtime._loop_finished.wait(timeout=1)
            runtime.close()

        with pytest.raises(McpRuntimeError):
            future.result(timeout=1)

    assert runtime._loop_finished.wait(timeout=1)
    assert runtime._owners == {}
    assert not start_file.exists()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_preflight_failure_close_never_waits_for_grace(tmp_path) -> None:
    class NoWaitEvent:
        def __init__(self) -> None:
            self.set_calls = 0

        def set(self) -> None:
            self.set_calls += 1

        def wait(self, timeout: float | None = None) -> bool:
            raise AssertionError(f"unexpected close wait: {timeout}")

    start_file = tmp_path / "started.txt"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_MISSING_TOKEN",),
        extra_args=("--start-file", str(start_file)),
    )
    loop_finished = NoWaitEvent()
    runtime._loop_finished = loop_finished

    with pytest.raises(McpRuntimeError):
        runtime.discover_tools()
    runtime.close()

    assert loop_finished.set_calls >= 1
    assert not start_file.exists()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_interrupted_discovery_requests_stop_before_close(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = McpStdioRuntime(
        tmp_path / "workspace",
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    runtime._state = "starting"
    order: list[str] = []
    monkeypatch.setattr(
        runtime,
        "_request_transport_stop",
        lambda: order.append("stop"),
    )
    monkeypatch.setattr(runtime, "_close_transport", lambda: order.append("close"))

    runtime._abort_discovery()

    assert order == ["stop", "close"]
    assert runtime._state == "failed"


def test_stdio_runtime_keyboard_interrupt_during_initial_wait_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = _runtime(
        tmp_path,
        mode="init-delay",
        extra_args=("--delay", "0.1"),
    )
    original_enqueue = runtime._enqueue
    interrupted = False

    def enqueue_with_interrupted_wait(server_id, command) -> None:
        nonlocal interrupted
        original_enqueue(server_id, command)
        if command.kind == "discover" and command.initial and not interrupted:
            interrupted = True

            def interrupt_result(timeout: float | None = None):
                raise KeyboardInterrupt

            command.future.result = interrupt_result

    monkeypatch.setattr(mcp_runtime_module, "_CLOSE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(runtime, "_enqueue", enqueue_with_interrupted_wait)

    with pytest.raises(KeyboardInterrupt):
        runtime.discover_tools()

    assert interrupted
    assert runtime._loop_finished.wait(timeout=1)
    _assert_runtime_stopped(runtime)
    with pytest.raises(McpRuntimeError) as exc_info:
        runtime.discover_tools()
    assert exc_info.value.stage == "discovery"
    runtime.close()


@pytest.mark.parametrize("failure", ["owner", "loop"])
def test_stdio_runtime_ready_session_failure_is_sticky(
    tmp_path,
    monkeypatch,
    failure: str,
) -> None:
    runtime = _runtime(tmp_path)
    if failure == "loop":
        original_loop_main = runtime._loop_main

        async def failing_loop_main(starts) -> None:
            await original_loop_main(starts)
            raise RuntimeError("simulated loop failure")

        monkeypatch.setattr(runtime, "_loop_main", failing_loop_main)
        monkeypatch.setattr(runtime, "_owner_finished", lambda _server_id: None)

    try:
        assert runtime.discover_tools()
        assert runtime._loop is not None
        if failure == "owner":
            runtime._loop.call_soon_threadsafe(runtime._owners["local"].cancel)
        else:
            assert runtime._stop_event is not None
            runtime._loop.call_soon_threadsafe(runtime._stop_event.set)

        assert runtime._loop_finished.wait(timeout=1)
        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == ("discovery" if failure == "owner" else "initialize")
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_close_uses_one_shared_deadline(tmp_path, monkeypatch) -> None:
    class WaitUntilDeadline:
        def __init__(self, clock: list[float]) -> None:
            self.clock = clock
            self.timeouts: list[float | None] = []

        def wait(self, timeout: float | None = None) -> bool:
            self.timeouts.append(timeout)
            self.clock[0] += timeout or 0
            return False

    class RecordingThread:
        def __init__(self) -> None:
            self.join_timeouts: list[float | None] = []

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

        @staticmethod
        def is_alive() -> bool:
            return False

    runtime = McpStdioRuntime(
        tmp_path / "workspace",
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    clock = [0.0]
    loop_ready = WaitUntilDeadline(clock)
    thread = RecordingThread()
    runtime._loop_ready = loop_ready
    runtime._thread = thread
    monkeypatch.setattr(mcp_runtime_module, "_CLOSE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(mcp_runtime_module.time, "monotonic", lambda: clock[0])

    runtime._close_transport()

    assert loop_ready.timeouts == [5.0]
    assert thread.join_timeouts == [0.0]
    runtime._thread = None
    runtime.close()


def test_stdio_runtime_processes_graceful_close_before_requesting_loop_stop(
    tmp_path,
    monkeypatch,
) -> None:
    order: list[str] = []

    class RecordingLoop:
        @staticmethod
        def call_soon_threadsafe(callback) -> None:
            callback()

    class RecordingStopEvent:
        @staticmethod
        def set() -> None:
            order.append("stop")

    class RecordingThread:
        @staticmethod
        def join(timeout: float | None = None) -> None:
            order.append("join")

        @staticmethod
        def is_alive() -> bool:
            return False

    runtime = McpStdioRuntime(
        tmp_path / "workspace",
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    runtime._starts = {"local": object()}
    runtime._loop = RecordingLoop()
    runtime._stop_event = RecordingStopEvent()
    runtime._thread = RecordingThread()
    runtime._loop_ready.set()

    def complete_close(_server_id, command) -> None:
        assert command.kind == "close"
        order.append("close")
        command.future.set_result(None)

    monkeypatch.setattr(runtime, "_enqueue", complete_close)

    runtime._close_transport()

    assert order == ["close", "stop", "join"]
    runtime._thread = None
    runtime.close()


def test_stdio_runtime_session_receive_failure_invalidates_ready_snapshot(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="malformed-after-list",
        extra_args=("--notify-delay", "0.03"),
    )
    try:
        assert runtime.discover_tools()
        assert runtime._loop_finished.wait(timeout=3)

        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        assert runtime._state == "failed"
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


@pytest.mark.parametrize("safety_failure", [False, True])
def test_stdio_runtime_refresh_rejects_result_if_owner_ended(
    tmp_path,
    monkeypatch,
    safety_failure: bool,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.discover_tools()
        runtime._mark_dirty("local")

        def finish_after_owner_ended(server_ids, *, initial: bool):
            assert tuple(server_ids) == ("local",)
            assert not initial
            with runtime._condition:
                runtime._dead_servers.add("local")
            if safety_failure:
                raise mcp_runtime_module._SnapshotSafetyError(
                    server_id="local",
                    message="Unsafe refreshed metadata.",
                )
            return {"local": runtime._server_snapshots["local"]}

        monkeypatch.setattr(runtime, "_dispatch_discovery", finish_after_owner_ended)

        with pytest.raises(McpRuntimeError) as exc_info:
            runtime.discover_tools()

        assert exc_info.value.stage == "discovery"
        assert runtime._state == "failed"
        assert runtime._loop_finished.wait(timeout=2)
        with pytest.raises(McpRuntimeError):
            runtime.discover_tools()
    finally:
        runtime.close()
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_reloads_entire_failed_refresh_batch_after_new_notification(
    tmp_path,
    monkeypatch,
) -> None:
    class AliveOwner:
        @staticmethod
        def done() -> bool:
            return False

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = Path(sys.executable).resolve()
    config_kwargs = {
        "command": executable,
        "args": (),
        "pass_env": (),
        "cwd": tmp_path,
        "subprocess_path": str(executable.parent),
        "subprocess_pathext": ".EXE;.COM" if os.name == "nt" else None,
    }
    runtime = McpStdioRuntime(
        workspace,
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    runtime._state = "ready"
    runtime._configs = (
        McpServerConfig(server_id="alpha", **config_kwargs),
        McpServerConfig(server_id="beta", **config_kwargs),
    )
    runtime._server_snapshots = {"alpha": (), "beta": ()}
    runtime._dirty_generation = {"alpha": 1, "beta": 1}
    runtime._published_generation = {"alpha": 0, "beta": 0}
    runtime._owners = {"alpha": AliveOwner(), "beta": AliveOwner()}
    dispatches: list[tuple[str, ...]] = []

    def reject_batch(server_ids, *, initial: bool):
        dispatches.append(tuple(server_ids))
        raise mcp_runtime_module._SnapshotSafetyError(
            server_id="alpha",
            message="Unsafe refreshed metadata.",
        )

    monkeypatch.setattr(runtime, "_dispatch_discovery", reject_batch)
    with pytest.raises(McpRuntimeError):
        runtime.discover_tools()
    assert dispatches == [("alpha", "beta")]

    with pytest.raises(McpRuntimeError):
        runtime.discover_tools()
    assert dispatches == [("alpha", "beta")]

    runtime._mark_dirty("alpha")

    def accept_batch(server_ids, *, initial: bool):
        dispatches.append(tuple(server_ids))
        return {server_id: () for server_id in server_ids}

    monkeypatch.setattr(runtime, "_dispatch_discovery", accept_batch)
    assert runtime.discover_tools() == ()
    assert dispatches[-1] == ("alpha", "beta")
    assert runtime._refresh_error is None
    runtime.close()


def test_prepare_server_starts_redacts_secrets_across_server_boundaries(tmp_path) -> None:
    executable = Path(sys.executable).resolve()

    def config(server_id: str, env_name: str) -> McpServerConfig:
        return McpServerConfig(
            server_id=server_id,
            command=executable,
            args=(),
            pass_env=(env_name,),
            cwd=tmp_path,
            subprocess_path=str(executable.parent),
            subprocess_pathext=".EXE;.COM" if os.name == "nt" else None,
        )

    alpha_secret = "alpha-secret-ef68313d"
    beta_secret = "beta-secret-c53f98b1"
    starts = mcp_runtime_module._prepare_server_starts(
        (config("alpha", "ALPHA_TOKEN"), config("beta", "BETA_TOKEN")),
        {
            **_safe_environment(),
            "ALPHA_TOKEN": alpha_secret,
            "BETA_TOKEN": beta_secret,
        },
    )
    assert "ALPHA_TOKEN" not in dict(starts[1].environment)
    assert starts[0].secrets is starts[1].secrets

    class Tool:
        name = "echo"
        description = f"cross-server value: {alpha_secret}"
        inputSchema = {"type": "object"}
        outputSchema = None

    definition = mcp_runtime_module._definitions_from_tools(
        "beta",
        [Tool()],
        starts[1].secrets,
    )[0]
    assert alpha_secret not in definition.description
    assert "[REDACTED]" in definition.description

    Tool.inputSchema = {"type": "object", "description": alpha_secret}
    with pytest.raises(mcp_runtime_module._SnapshotSafetyError):
        mcp_runtime_module._definitions_from_tools(
            "beta",
            [Tool()],
            starts[1].secrets,
        )


def test_stdio_runtime_close_interruption_still_stops_loop_and_reaches_closed(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = _runtime(tmp_path)
    assert runtime.discover_tools()
    original_enqueue = runtime._enqueue
    interrupted = False

    def enqueue_with_interrupted_wait(server_id, command) -> None:
        nonlocal interrupted
        original_enqueue(server_id, command)
        if command.kind == "close" and not interrupted:
            interrupted = True

            def interrupt_result(timeout: float | None = None):
                raise KeyboardInterrupt

            command.future.result = interrupt_result

    monkeypatch.setattr(runtime, "_enqueue", enqueue_with_interrupted_wait)

    with pytest.raises(KeyboardInterrupt):
        runtime.close()

    assert interrupted
    assert runtime._state == "closed"
    assert runtime._loop_finished.wait(timeout=2)
    _assert_runtime_stopped(runtime)
    runtime.close()


def test_stdio_runtime_close_timeout_does_not_claim_closed_and_can_retry(tmp_path) -> None:
    class SlowThread:
        def __init__(self) -> None:
            self.alive = True
            self.join_calls = 0

        def join(self, timeout: float | None = None) -> None:
            self.join_calls += 1

        def is_alive(self) -> bool:
            return self.alive

    runtime = McpStdioRuntime(
        tmp_path / "workspace",
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    thread = SlowThread()
    runtime._state = "ready"
    runtime._thread = thread
    runtime._loop_ready.set()

    with pytest.raises(McpRuntimeError) as exc_info:
        runtime.close()

    assert exc_info.value.stage == "runtime"
    assert runtime._state == "failed"
    assert thread.join_calls == 1

    thread.alive = False
    runtime._loop_finished.set()
    runtime.close()
    assert runtime._state == "closed"


@pytest.mark.parametrize("phase", ["initial", "refresh"])
def test_stdio_runtime_cleanup_timeout_does_not_leave_discovery_waiters_blocked(
    tmp_path,
    monkeypatch,
    phase: str,
) -> None:
    runtime = McpStdioRuntime(
        tmp_path / "workspace",
        home=tmp_path / "home",
        environ=_safe_environment(),
    )
    discovery_error = McpRuntimeError(
        stage="discovery",
        server_id="local",
        message="Simulated discovery failure.",
    )

    def fail_cleanup() -> None:
        raise mcp_runtime_module._transport_cleanup_error()

    monkeypatch.setattr(runtime, "_close_transport", fail_cleanup)
    if phase == "initial":
        runtime._state = "starting"
        fail = lambda: runtime._fail_initial(discovery_error)
    else:
        runtime._state = "ready"
        runtime._refreshing = True

        def fail_dispatch(_server_ids, *, initial: bool):
            raise discovery_error

        monkeypatch.setattr(runtime, "_dispatch_discovery", fail_dispatch)
        fail = lambda: runtime._refresh_discovery({"local": 1})

    with pytest.raises(McpRuntimeError) as exc_info:
        fail()

    assert exc_info.value.stage == "runtime"
    assert runtime._state == "failed"
    assert not runtime._refreshing
    with pytest.raises(McpRuntimeError):
        runtime.discover_tools()


def test_stdio_runtime_close_releases_runtime_owned_secrets_and_snapshot(tmp_path) -> None:
    secret = "close-secret-cf593641"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_TOKEN",),
        environ={"MCP_TOKEN": secret},
    )
    definitions = runtime.discover_tools()
    assert secret in runtime._starts["local"].secrets.values

    runtime.close()

    assert definitions
    assert runtime._state == "closed"
    assert runtime._snapshot == ()
    assert runtime._server_snapshots == {}
    assert runtime._starts == {}
    assert runtime._configs == ()
    assert runtime._environ is None
    assert runtime._owners == {}
    assert runtime._thread is None

def _call_payload(result: McpCallResult) -> str:
    return json.dumps(
        {
            "status": result.status,
            "summary": result.summary,
            "data": result.data,
            "diagnostic_details": result.diagnostic_details,
            "redaction_replacements": result.redaction_replacements,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _wait_for_runtime_state(
    runtime: McpStdioRuntime,
    state: str,
    *,
    timeout: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runtime._state == state:
            return
        time.sleep(0.01)
    raise AssertionError(f"runtime did not reach {state!r}: {runtime._state!r}")


def test_stdio_runtime_calls_real_fixture_and_keeps_tool_errors_healthy(tmp_path) -> None:
    runtime = _runtime(tmp_path, mode="call-results")
    target = runtime.discover_tools()[0].target
    try:
        success = runtime.call_tool(target, {"message": "hello"})
        tool_error = runtime.call_tool(target, {"message": "tool-error"})
        success_after_error = runtime.call_tool(target, {"message": "again"})
    finally:
        runtime.close()

    assert success.status == "ok"
    assert success.summary == "hello"
    assert success.data == {
        "content": [{"type": "text", "text": "hello"}],
        "structured_content": {"message": "hello"},
    }
    assert tool_error.status == "tool_error"
    assert tool_error.summary == "business failure"
    assert success_after_error.status == "ok"


def test_stdio_runtime_normalizes_rich_results_and_redacts_every_public_copy(tmp_path) -> None:
    secret = "runtime-call-secret-f83f"
    runtime = _runtime(
        tmp_path,
        mode="call-results",
        pass_env=("MCP_TOKEN",),
        environ={"MCP_TOKEN": secret},
    )
    target = runtime.discover_tools()[0].target
    try:
        redacted = runtime.call_tool(target, {"message": secret})
        rich = runtime.call_tool(target, {"message": "rich"})
    finally:
        runtime.close()

    redacted_payload = _call_payload(redacted)
    assert redacted.status == "ok"
    assert secret not in redacted_payload
    assert redacted_payload.count("[REDACTED]") == 3
    assert redacted.redaction_replacements == 3

    assert rich.status == "ok"
    assert rich.data is not None
    rich_payload = json.dumps(rich.data, ensure_ascii=False)
    assert "discard-me" not in rich_payload
    assert "YWJj" not in rich_payload
    assert "MTI=" not in rich_payload
    assert "YmxvYg==" not in rich_payload
    assert rich.data["content"][1] == {
        "type": "image",
        "mime_type": "image/png",
        "size": 3,
        "omitted": True,
    }
    assert rich.data["content"][2]["size"] == 2
    assert rich.data["content"][4]["resource"]["text"] == "embedded text"
    assert rich.data["content"][5]["resource"]["size"] == 4
    assert rich.data["content"][5]["resource"]["omitted"] is True


def test_stdio_runtime_output_validation_failure_poison_server_without_leaking_data(tmp_path) -> None:
    call_file = tmp_path / "calls.txt"
    runtime = _runtime(
        tmp_path,
        mode="call-results",
        output_schema="valid",
        extra_args=("--call-file", str(call_file)),
    )
    target = runtime.discover_tools()[0].target
    try:
        result = runtime.call_tool(target, {"message": "invalid-output"})
        _wait_for_runtime_state(runtime, "failed")
        failed_fast = runtime.call_tool(target, {"message": "must-not-run"})
    finally:
        runtime.close()

    assert result.status == "failed"
    assert result.data is None
    assert result.diagnostic_details == {
        "stage": "output_validation",
        "path": "$.message",
        "validator": "type",
    }
    assert "42" not in _call_payload(result)
    assert failed_fast.status == "failed"
    assert len(call_file.read_text(encoding="utf-8").splitlines()) == 1


def test_stdio_runtime_queue_timeout_cancels_before_request_start(tmp_path) -> None:
    call_file = tmp_path / "calls.txt"
    runtime = _runtime(
        tmp_path,
        mode="call-delay",
        extra_args=("--delay", "0.25", "--call-file", str(call_file)),
    )
    target = runtime.discover_tools()[0].target
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(
                runtime.call_tool,
                target,
                {"message": "active"},
                timeout_seconds=1.0,
            )
            _wait_for_file(call_file)
            queued = runtime.call_tool(
                target,
                {"message": "queued"},
                timeout_seconds=0.05,
            )
            active_result = active.result(timeout=2.0)
    finally:
        runtime.close()

    assert queued.status == "timeout"
    assert queued.diagnostic_details == {"stage": "queue_timeout"}
    assert active_result.status == "ok"
    assert len(call_file.read_text(encoding="utf-8").splitlines()) == 1


def test_stdio_runtime_request_timeout_closes_server_and_never_retries(tmp_path) -> None:
    call_file = tmp_path / "calls.txt"
    runtime = _runtime(
        tmp_path,
        mode="call-delay",
        extra_args=("--delay", "0.5", "--call-file", str(call_file)),
    )
    target = runtime.discover_tools()[0].target
    result = runtime.call_tool(target, {"message": "slow"}, timeout_seconds=0.05)
    failed_fast = runtime.call_tool(target, {"message": "must-not-run"})
    runtime.close()

    assert result.status == "timeout"
    assert result.diagnostic_details == {"stage": "request_timeout"}
    assert failed_fast.status == "failed"
    assert len(call_file.read_text(encoding="utf-8").splitlines()) == 1
    _assert_runtime_stopped(runtime)


def test_stdio_runtime_transport_failure_does_not_retry(tmp_path) -> None:
    call_file = tmp_path / "calls.txt"
    runtime = _runtime(
        tmp_path,
        mode="call-crash",
        extra_args=("--call-file", str(call_file)),
    )
    target = runtime.discover_tools()[0].target
    try:
        result = runtime.call_tool(target, {"message": "crash"})
        _wait_for_runtime_state(runtime, "failed")
        failed_fast = runtime.call_tool(target, {"message": "must-not-run"})
    finally:
        runtime.close()

    assert result.status == "failed"
    assert result.diagnostic_details == {"stage": "request"}
    assert failed_fast.status == "failed"
    assert len(call_file.read_text(encoding="utf-8").splitlines()) == 1


def test_stdio_runtime_serializes_same_server_but_allows_different_servers(tmp_path) -> None:
    delay = 0.25
    (tmp_path / "same").mkdir()
    same_runtime = _runtime(
        tmp_path / "same",
        mode="call-delay",
        extra_args=("--delay", str(delay)),
    )
    same_target = same_runtime.discover_tools()[0].target
    try:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    same_runtime.call_tool,
                    same_target,
                    {"message": str(index)},
                    timeout_seconds=2.0,
                )
                for index in range(2)
            ]
            assert [future.result(timeout=3.0).status for future in futures] == ["ok", "ok"]
        same_elapsed = time.monotonic() - started
    finally:
        same_runtime.close()

    root = tmp_path / "different"
    workspace = root / "workspace"
    home = root / "home"
    workspace.mkdir(parents=True)
    args = [
        str(_STDIO_FIXTURE),
        "--mode",
        "call-delay",
        "--delay",
        str(delay),
    ]
    server = (
        "command = " + _toml_string(Path(sys.executable).resolve()) + "\n"
        + "args = " + json.dumps(args) + "\n"
        + "pass_env = []\n"
    )
    _write_config(home, "[servers.one]\n" + server + "[servers.two]\n" + server)
    different_runtime = McpStdioRuntime(
        workspace,
        home=home,
        environ=_safe_environment(),
    )
    targets = [definition.target for definition in different_runtime.discover_tools()]
    try:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    different_runtime.call_tool,
                    target,
                    {"message": target.server_id},
                    timeout_seconds=2.0,
                )
                for target in targets
            ]
            assert [future.result(timeout=3.0).status for future in futures] == ["ok", "ok"]
        different_elapsed = time.monotonic() - started
    finally:
        different_runtime.close()

    assert same_elapsed >= delay * 1.8
    assert different_elapsed < delay * 1.7


def test_stdio_runtime_old_snapshot_target_survives_rejected_refresh(tmp_path) -> None:
    runtime = _runtime(
        tmp_path,
        mode="list-changed-unsafe",
        output_schema="valid",
        extra_args=("--notify-delay", "0.05"),
    )
    old_target = runtime.discover_tools()[0].target
    deadline = time.monotonic() + 2.0
    while runtime._dirty_generation.get("local", 0) == 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    with pytest.raises(McpRuntimeError):
        runtime.discover_tools()
    try:
        result = runtime.call_tool(old_target, {"message": "snapshot-one"})
    finally:
        runtime.close()

    assert result.status == "ok"
    assert result.data is not None
    assert result.data["structured_content"] == {"message": "snapshot-one"}


def test_stdio_runtime_sdk_error_redaction_and_unknown_block_are_bounded(tmp_path) -> None:
    secret = "sdk-error-secret-c129"
    runtime = _runtime(
        tmp_path,
        pass_env=("MCP_TOKEN",),
        environ={"MCP_TOKEN": secret},
    )
    target = runtime.discover_tools()[0].target
    start = runtime._starts["local"]

    class FailingSession:
        async def send_request(self, *_args, **_kwargs):
            raise RuntimeError(f"SDK failed with {secret}")

    command = mcp_runtime_module._OwnerCommand(
        kind="call",
        future=mcp_runtime_module.concurrent.futures.Future(),
        target=target,
        arguments={"message": "ignored"},
    )
    outcome = asyncio.run(runtime._call_remote_tool(FailingSession(), start, command))
    runtime.close()

    payload = _call_payload(outcome.result)
    assert outcome.poison_server is True
    assert outcome.result.status == "failed"
    assert outcome.result.redaction_replacements == 1
    assert secret not in payload

    class FutureBlock:
        type = "future-content"
        raw = secret

    normalized, summary = mcp_runtime_module._normalize_content_block(FutureBlock())
    assert normalized == {"type": "unknown", "omitted": True}
    assert summary is None
