from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

import agent._user_store as user_store_module
import agent.mcp_config as mcp_config_module
from agent.mcp_config import McpConfigStore, McpRuntimeError, McpServerConfig, load_mcp_server_configs


_CRASH_FIXTURE = (Path(__file__).parent / "fixtures" / "extension_crash_worker.py").resolve()


def _toml_string(value: str | Path) -> str:
    return json.dumps(str(value))


def _safe_environment() -> dict[str, str]:
    executable_dir = Path(sys.executable).resolve().parent
    return {"PATH": str(executable_dir), "PATHEXT": ".EXE;.COM"}


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


def _write_manual(home: Path, server_id: str = "manual") -> Path:
    return _write_config(
        home,
        f"[servers.{server_id}]\n"
        f"command = {_toml_string(Path(sys.executable).resolve())}\n"
        "args = []\n"
        "pass_env = []\n",
    )


def _make_store(tmp_path: Path) -> tuple[McpConfigStore, Path, Path]:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir(parents=True)
    home.mkdir(parents=True)
    return McpConfigStore(workspace, home=home, environ=_safe_environment()), workspace, home


def _set(store: McpConfigStore, server_id: str, *, args: tuple[str, ...] = ()) -> None:
    store.set_server(
        server_id,
        command=str(Path(sys.executable).resolve()),
        args=args,
        pass_env=(),
        cwd="config",
    )


def test_managed_static_lifecycle_is_atomic_and_preserves_disabled_replace(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)

    _set(store, "alpha", args=("v1",))

    fragment = home / ".agent" / "mcp.d" / "alpha.toml"
    assert tomllib.loads(fragment.read_text(encoding="utf-8")) == {
        "command": str(Path(sys.executable).resolve()),
        "args": ["v1"],
        "pass_env": [],
        "cwd": "config",
    }
    assert [(item.server_id, item.source, item.enabled, item.status) for item in store.inventory()] == [
        ("alpha", "managed", True, "valid")
    ]

    store.set_enabled("alpha", False)
    _set(store, "alpha", args=("v2",))

    assert store.load_enabled_configs() == ()
    assert store.inventory()[0].status == "disabled"

    store.set_enabled("alpha", True)
    assert store.load_enabled_configs()[0].args == ("v2",)

    store.remove_server("alpha")
    assert store.inventory() == ()
    assert not fragment.exists()
    state = home / ".agent" / "mcp-state.json"
    assert not state.exists() or "alpha" not in state.read_text(encoding="utf-8")


def test_manual_and_managed_merge_without_mutating_manual_config(tmp_path) -> None:
    store, workspace, home = _make_store(tmp_path)
    manual = _write_manual(home)
    original = manual.read_bytes()

    _set(store, "zeta")
    _set(store, "alpha")

    configs = store.load_enabled_configs()
    assert [config.server_id for config in configs] == ["manual", "alpha", "zeta"]
    assert all(isinstance(config, McpServerConfig) for config in configs)
    assert manual.read_bytes() == original
    with pytest.raises(McpRuntimeError, match="manual"):
        _set(store, "manual")
    with pytest.raises(McpRuntimeError, match="manual"):
        store.remove_server("manual")

    assert load_mcp_server_configs(workspace, home=home, environ=_safe_environment()) == configs


def test_validate_accepts_legacy_manual_id_longer_than_managed_limit(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    server_id = "m" * 65
    _write_manual(home, server_id)

    assert store.validate(server_id)[0].server_id == server_id
    assert store.set_enabled(server_id, False).status == "disabled"
    assert store.load_enabled_configs() == ()
    assert store.set_enabled(server_id, True).status == "valid"


def test_disabled_bad_command_is_visible_but_not_loaded_or_started(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    _set(store, "broken")
    store.set_enabled("broken", False)
    fragment = home / ".agent" / "mcp.d" / "broken.toml"
    fragment.write_text('command = "definitely-missing-command"\n', encoding="utf-8")

    assert store.load_enabled_configs() == ()
    assert store.inventory()[0].status == "disabled"
    with pytest.raises(McpRuntimeError, match="not found"):
        store.validate("broken")
    with pytest.raises(McpRuntimeError, match="not found"):
        store.set_enabled("broken", True)
    assert store.inventory()[0].enabled is False


def test_state_only_orphan_is_non_blocking_and_has_deterministic_cleanup(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    agent_root.mkdir()
    (agent_root / "mcp-state.json").write_text('{"version":1,"disabled":["ghost"]}\n', encoding="utf-8")

    assert store.load_enabled_configs() == ()
    orphan = store.inventory()[0]
    assert (orphan.server_id, orphan.source, orphan.enabled, orphan.status) == (
        "ghost",
        "orphan",
        False,
        "orphan",
    )
    with pytest.raises(McpRuntimeError, match="does not exist"):
        store.set_enabled("ghost", True)

    store.remove_server("ghost")
    assert store.inventory() == ()

    (agent_root / "mcp-state.json").write_text('{"version":1,"disabled":["ghost"]}\n', encoding="utf-8")
    _set(store, "ghost")
    assert store.inventory()[0].enabled is True


def test_missing_enable_and_idempotent_remove_do_not_create_user_storage(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)

    with pytest.raises(McpRuntimeError, match="does not exist"):
        store.set_enabled("missing", True)
    store.remove_server("missing")

    assert not (home / ".agent").exists()


def test_invalid_set_is_validated_before_user_storage_is_created(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)

    with pytest.raises(McpRuntimeError, match="not found"):
        store.set_server("broken", command="definitely-missing-command")

    assert not (home / ".agent").exists()


@pytest.mark.parametrize(
    "state",
    [
        '{"version":2,"disabled":[]}',
        '{"version":1,"disabled":[],"extra":true}',
        '{"version":1,"disabled":"alpha"}',
        '{"version":1,"disabled":["bad id"]}',
    ],
)
def test_invalid_state_fails_closed(tmp_path, state: str) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    agent_root.mkdir()
    (agent_root / "mcp-state.json").write_text(state, encoding="utf-8")

    with pytest.raises(McpRuntimeError, match="state"):
        store.inventory()


def test_manual_managed_and_casefold_fragment_conflicts_fail_closed(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    _write_manual(home, "alpha")
    fragments = home / ".agent" / "mcp.d"
    fragments.mkdir()
    content = f"command = {_toml_string(Path(sys.executable).resolve())}\n"
    (fragments / "alpha.toml").write_text(content, encoding="utf-8")

    with pytest.raises(McpRuntimeError, match="both manual and managed"):
        store.inventory()

    (home / ".agent" / "mcp.toml").unlink()
    if os.name == "nt":
        return
    (fragments / "Alpha.toml").write_text(content, encoding="utf-8")
    with pytest.raises(McpRuntimeError, match="case"):
        store.inventory()


def test_set_rejects_casefold_collision_before_touching_existing_fragment(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    _set(store, "alpha", args=("original",))
    fragment = home / ".agent" / "mcp.d" / "alpha.toml"
    before = fragment.read_bytes()

    with pytest.raises(McpRuntimeError, match="case folding"):
        _set(store, "Alpha", args=("replacement",))

    assert fragment.read_bytes() == before
    assert store.load_enabled_configs()[0].args == ("original",)


def test_set_rejects_casefold_collision_with_manual_source(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    _write_manual(home, "Alpha")

    with pytest.raises(McpRuntimeError, match="case folding"):
        _set(store, "alpha")

    assert not (home / ".agent" / "mcp.d" / "alpha.toml").exists()


def test_orphans_do_not_count_toward_eight_server_limit(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    agent_root.mkdir()
    disabled = [f"orphan{index}" for index in range(20)]
    (agent_root / "mcp-state.json").write_text(
        json.dumps({"version": 1, "disabled": disabled}),
        encoding="utf-8",
    )
    for index in range(8):
        _set(store, f"server{index}")

    assert len(store.load_enabled_configs()) == 8
    with pytest.raises(McpRuntimeError, match="8"):
        _set(store, "server8")


def test_atomic_state_publish_failure_keeps_previous_bytes(tmp_path, monkeypatch) -> None:
    store, _, home = _make_store(tmp_path)
    _set(store, "alpha")
    store.set_enabled("alpha", False)
    state = home / ".agent" / "mcp-state.json"
    before = state.read_bytes()
    real_replace = os.replace

    def fail_state_replace(source, target) -> None:
        if Path(target) == state:
            raise OSError("simulated publish failure")
        real_replace(source, target)

    monkeypatch.setattr(mcp_config_module.os, "replace", fail_state_replace)

    with pytest.raises(McpRuntimeError, match="write"):
        store.set_enabled("alpha", True)

    assert state.read_bytes() == before
    assert not list(state.parent.glob(f".{state.name}.agent-*"))


# Directory-sync failure is covered once against the shared primitive in
# tests/test_user_store.py; MCP only adapts the error type.


def test_managed_store_rejects_linked_fragment_directory(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    target = tmp_path / "external"
    agent_root.mkdir()
    target.mkdir()
    try:
        (agent_root / "mcp.d").symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(McpRuntimeError, match="link|reparse"):
        store.inventory()


@pytest.mark.parametrize("name", ["mcp-state.json", ".extension.lock"])
def test_managed_store_rejects_linked_state_and_lock_files(tmp_path, name: str) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    target = tmp_path / f"target-{name.replace('.', '_')}"
    agent_root.mkdir()
    target.write_text('{"version":1,"disabled":[]}\n' if name == "mcp-state.json" else "0", encoding="utf-8")
    try:
        (agent_root / name).symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(McpRuntimeError, match="link|reparse"):
        store.inventory()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics")
def test_managed_store_rejects_junction_agent_root(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    external = tmp_path / "external-agent"
    external.mkdir()
    (external / "mcp-state.json").write_text('{"version":1,"disabled":[]}\n', encoding="utf-8")
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(home / ".agent"), str(external)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable")

    with pytest.raises(McpRuntimeError, match="link|reparse"):
        store.inventory()


@pytest.mark.parametrize("server_id", ["CON", "bad.id", "x" * 65])
def test_set_rejects_unsafe_managed_ids_before_creating_a_fragment(tmp_path, server_id: str) -> None:
    store, _, home = _make_store(tmp_path)

    with pytest.raises(McpRuntimeError, match="safe 1-64"):
        _set(store, server_id)

    assert not (home / ".agent" / "mcp.d" / f"{server_id}.toml").exists()


def test_lock_timeout_and_os_release_after_holder_termination(tmp_path, monkeypatch) -> None:
    store, workspace, home = _make_store(tmp_path)
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "hold-lock",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--ready",
            str(ready),
        ]
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        monkeypatch.setattr(user_store_module, "LOCK_TIMEOUT_SECONDS", 0.05)
        with pytest.raises(McpRuntimeError, match="busy"):
            store.inventory()
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert store.inventory() == ()


@pytest.mark.parametrize(
    ("crash_at", "expected_args"),
    [
        ("candidate", ("v1",)),
        ("prepared", ("v1",)),
        ("backup", ("v1",)),
        ("target", ("v1",)),
        ("state", ("v1",)),
        ("committed", ("v2",)),
        ("cleanup", ("v2",)),
    ],
)
def test_set_recovers_after_process_exit_at_each_transaction_phase(
    tmp_path,
    crash_at: str,
    expected_args: tuple[str, ...],
) -> None:
    store, workspace, home = _make_store(tmp_path)
    _set(store, "alpha", args=("v1",))

    result = subprocess.run(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "crash-set",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--crash-at",
            crash_at,
        ],
        check=False,
        timeout=10,
    )

    assert result.returncode == 91
    assert store.load_enabled_configs()[0].args == expected_args
    transactions = home / ".agent" / ".extension-transactions"
    assert not transactions.exists() or not list(transactions.iterdir())
    assert not list((home / ".agent").glob(".mcp-state.json.agent-*"))


@pytest.mark.parametrize(
    ("crash_at", "expected_present"),
    [
        ("prepared", True),
        ("backup", True),
        ("state", True),
        ("committed", False),
        ("cleanup", False),
    ],
)
def test_remove_recovers_after_process_exit_at_each_transaction_phase(
    tmp_path,
    crash_at: str,
    expected_present: bool,
) -> None:
    store, workspace, home = _make_store(tmp_path)
    _set(store, "alpha", args=("v1",))

    result = subprocess.run(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "crash-remove",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--crash-at",
            crash_at,
        ],
        check=False,
        timeout=10,
    )

    assert result.returncode == 91
    assert bool(store.load_enabled_configs()) is expected_present
    transactions = home / ".agent" / ".extension-transactions"
    assert not transactions.exists() or not list(transactions.iterdir())


def test_prepared_set_recovery_keeps_backup_until_state_is_restored(tmp_path, monkeypatch) -> None:
    store, workspace, home = _make_store(tmp_path)
    _set(store, "alpha", args=("v1",))
    result = subprocess.run(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "crash-set",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--crash-at",
            "target",
        ],
        check=False,
        timeout=10,
    )
    assert result.returncode == 91
    tx = next((home / ".agent" / ".extension-transactions").iterdir())
    real_write_state = store._write_state
    attempts = 0

    def fail_once(root: Path, disabled: set[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise McpRuntimeError(stage="config", server_id=None, message="injected state failure")
        real_write_state(root, disabled)

    monkeypatch.setattr(store, "_write_state", fail_once)
    with pytest.raises(McpRuntimeError, match="injected state failure"):
        store.inventory()

    assert (tx / "backup.toml").is_file()
    assert store.load_enabled_configs()[0].args == ("v1",)


def test_missing_transaction_record_never_deletes_an_existing_backup(tmp_path) -> None:
    store, workspace, home = _make_store(tmp_path)
    _set(store, "alpha", args=("v1",))
    result = subprocess.run(
        [
            sys.executable,
            str(_CRASH_FIXTURE),
            "crash-set",
            "--workspace",
            str(workspace),
            "--home",
            str(home),
            "--crash-at",
            "backup",
        ],
        check=False,
        timeout=10,
    )
    assert result.returncode == 91
    tx = next((home / ".agent" / ".extension-transactions").iterdir())
    (tx / "record.json").unlink()

    with pytest.raises(McpRuntimeError, match="backup.*manual recovery"):
        store.inventory()

    assert (tx / "backup.toml").is_file()
    assert not (home / ".agent" / "mcp.d" / "alpha.toml").exists()


def test_unowned_transaction_and_prefix_temp_are_preserved(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    agent_root = home / ".agent"
    tx = agent_root / ".extension-transactions" / f"mcp-{'a' * 32}"
    tx.mkdir(parents=True)
    candidate = tx / "candidate.toml"
    candidate.write_text('command = "untrusted"\n', encoding="utf-8")
    prefix_temp = agent_root / ".mcp-state.json.agent-not-owned"
    prefix_temp.write_text("untrusted\n", encoding="utf-8")

    with pytest.raises(McpRuntimeError, match="ownership marker"):
        store.inventory()

    assert candidate.is_file()
    assert prefix_temp.is_file()


def test_valid_transaction_record_without_owner_cannot_mutate_target_or_state(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    _set(store, "alpha", args=("v1",))
    agent_root = home / ".agent"
    fragment = agent_root / "mcp.d" / "alpha.toml"
    state = agent_root / "mcp-state.json"
    fragment_before = fragment.read_bytes()
    state_before = state.read_bytes()
    tx = agent_root / ".extension-transactions" / f"mcp-{'b' * 32}"
    tx.mkdir(parents=True)
    (tx / "record.json").write_text(
        json.dumps(
            {
                "version": 1,
                "module": "mcp",
                "operation": "set",
                "server_id": "alpha",
                "old_disabled": False,
                "old_fragment": False,
                "phase": "prepared",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(McpRuntimeError, match="ownership marker"):
        store.inventory()

    assert fragment.read_bytes() == fragment_before
    assert state.read_bytes() == state_before
    assert (tx / "record.json").is_file()


def test_owner_write_failure_cleans_current_transaction_and_allows_retry(tmp_path, monkeypatch) -> None:
    store, _, home = _make_store(tmp_path)
    real_write_new_file = user_store_module.write_new_file
    failed = False

    def fail_owner_once(path: Path, data: bytes) -> None:
        nonlocal failed
        if path.name == ".owner" and not failed:
            failed = True
            raise user_store_module.UserStoreError("injected owner failure")
        real_write_new_file(path, data)

    monkeypatch.setattr(user_store_module, "write_new_file", fail_owner_once)
    with pytest.raises(McpRuntimeError, match="injected owner failure"):
        _set(store, "alpha")

    transactions = home / ".agent" / ".extension-transactions"
    assert not transactions.exists() or not list(transactions.iterdir())
    _set(store, "alpha")
    assert store.load_enabled_configs()[0].server_id == "alpha"


def test_transaction_directory_uuid_collision_preserves_existing_evidence(tmp_path, monkeypatch) -> None:
    store, _, home = _make_store(tmp_path)
    tx_name = f"mcp-{'c' * 32}"
    evidence = home / ".agent" / ".extension-transactions" / tx_name / "evidence.txt"

    def colliding_uuid():
        evidence.parent.mkdir()
        evidence.write_text("keep\n", encoding="utf-8")
        return user_store_module.uuid.UUID(hex="c" * 32)

    monkeypatch.setattr(user_store_module.uuid, "uuid4", colliding_uuid)

    with pytest.raises(McpRuntimeError, match="transaction directory"):
        _set(store, "alpha")

    assert evidence.read_text(encoding="utf-8") == "keep\n"


def test_malformed_and_multiple_transactions_fail_closed_without_deleting_evidence(tmp_path) -> None:
    store, _, home = _make_store(tmp_path)
    transactions = home / ".agent" / ".extension-transactions"
    first = transactions / f"mcp-{'1' * 32}"
    first.mkdir(parents=True)
    (first / ".owner").write_bytes(mcp_config_module._TRANSACTION_OWNER)
    (first / "record.json").write_text("{}", encoding="utf-8")

    with pytest.raises(McpRuntimeError, match="unknown or missing fields"):
        store.inventory()
    assert (first / "record.json").exists()

    second = transactions / f"mcp-{'2' * 32}"
    second.mkdir()
    with pytest.raises(McpRuntimeError, match="Multiple MCP transactions"):
        store.inventory()
    assert first.exists() and second.exists()

def test_missing_user_config_returns_empty_and_ignores_project_config(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_config(workspace, _valid_server())

    assert load_mcp_server_configs(workspace, home=home, environ={}) == ()
    assert not home.exists()


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
