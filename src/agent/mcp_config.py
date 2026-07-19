from __future__ import annotations

import errno
import json
import os
import re
import stat
import time
import tomllib
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal


_MAX_SERVERS = 8
_MAX_STATE_BYTES = 64 * 1024
_SERVER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_SERVER_FIELDS = {"command", "args", "pass_env", "cwd"}
_WINDOWS_NATIVE_EXTENSIONS = {".COM", ".EXE"}
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_STARTUP_PATH = os.environ.get("PATH", "")
_STARTUP_PATHEXT = os.environ.get("PATHEXT")
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.05
_STATE_FIELDS = {"version", "disabled"}
_TRANSACTION_FIELDS = {
    "version",
    "module",
    "operation",
    "server_id",
    "old_disabled",
    "old_fragment",
    "phase",
}
_TRANSACTION_OWNER = b"agent:mcp-transaction:v1\n"
_TRANSACTION_OWNER_NAME = ".owner"
_TRANSACTION_NAME_PATTERN = re.compile(r"mcp-[0-9a-f]{32}\Z", re.ASCII)
_TEMP_NAME_PATTERN = re.compile(r"[0-9a-f]{32}\.tmp\Z", re.ASCII)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

McpConfigSource = Literal["manual", "managed", "orphan"]


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    server_id: str
    command: Path
    args: tuple[str, ...]
    pass_env: tuple[str, ...]
    cwd: Path
    subprocess_path: str
    subprocess_pathext: str | None


@dataclass(frozen=True, slots=True)
class McpInventoryItem:
    server_id: str
    source: McpConfigSource
    enabled: bool
    status: Literal["valid", "invalid", "disabled", "orphan"]
    message: str | None = None


class McpRuntimeError(RuntimeError):
    def __init__(self, *, stage: str, server_id: str | None, message: str) -> None:
        self.stage = stage
        self.server_id = server_id
        self.message = message
        prefix = f"MCP {stage} failed"
        if server_id is not None:
            prefix += f" for server {server_id!r}"
        super().__init__(f"{prefix}: {message}")


@dataclass(frozen=True, slots=True)
class _RawServer:
    server_id: str
    source: Literal["manual", "managed"]
    values: Any
    config_dir: Path


@dataclass(frozen=True, slots=True)
class _StoreSnapshot:
    servers: tuple[_RawServer, ...]
    disabled: frozenset[str]


class McpConfigStore:
    def __init__(
        self,
        workspace: Path,
        *,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._workspace = _resolve_workspace(workspace)
        self._raw_home = (Path(home) if home is not None else Path.home()).expanduser()
        try:
            self._home = self._raw_home.resolve()
        except (OSError, RuntimeError) as exc:
            raise _config_error("User home directory cannot be resolved.") from exc
        self._environ = dict(environ) if environ is not None else None

    def inventory(self) -> tuple[McpInventoryItem, ...]:
        with self._locked() as root:
            snapshot = self._read_snapshot(root)
            return self._inventory(snapshot)

    def validate(self, server_id: str | None = None) -> tuple[McpInventoryItem, ...]:
        if server_id is not None:
            _validate_server_id(server_id)
        with self._locked() as root:
            snapshot = self._read_snapshot(root)
            selected = tuple(raw for raw in snapshot.servers if server_id is None or raw.server_id == server_id)
            if server_id is not None and not selected:
                raise _config_error("Server does not exist.", server_id=server_id)
            configs = self._parse_servers(selected)
            for config in configs:
                self._validate_environment(config)
            return tuple(
                McpInventoryItem(
                    server_id=raw.server_id,
                    source=raw.source,
                    enabled=raw.server_id not in snapshot.disabled,
                    status="valid",
                )
                for raw in selected
            )

    def load_enabled_configs(self) -> tuple[McpServerConfig, ...]:
        with self._locked() as root:
            snapshot = self._read_snapshot(root)
            enabled: list[_RawServer] = []
            for raw in snapshot.servers:
                if raw.server_id in snapshot.disabled:
                    _validate_server_shape(raw)
                else:
                    enabled.append(raw)
            return self._parse_servers(tuple(enabled))

    def set_server(
        self,
        server_id: str,
        *,
        command: str,
        args: tuple[str, ...] = (),
        pass_env: tuple[str, ...] = (),
        cwd: Literal["config", "workspace"] = "config",
    ) -> McpInventoryItem:
        _validate_managed_id(server_id)
        values = {"command": command, "args": list(args), "pass_env": list(pass_env), "cwd": cwd}
        raw = _RawServer(
            server_id=server_id,
            source="managed",
            values=values,
            config_dir=self._home / ".agent" / "mcp.d",
        )
        config = self._parse_servers((raw,))[0]
        self._validate_environment(config)
        content = _serialize_fragment(values, server_id=server_id)
        with self._locked(create=True) as root:
            assert root is not None
            snapshot = self._read_snapshot(root)
            if any(raw.server_id == server_id and raw.source == "manual" for raw in snapshot.servers):
                raise _config_error("A manual Server must be migrated by editing mcp.toml.", server_id=server_id)
            source_collision = next(
                (
                    raw.server_id
                    for raw in snapshot.servers
                    if raw.server_id.casefold() == server_id.casefold()
                    and raw.server_id != server_id
                ),
                None,
            )
            state_collision = next(
                (
                    disabled_id
                    for disabled_id in snapshot.disabled
                    if disabled_id.casefold() == server_id.casefold() and disabled_id != server_id
                ),
                None,
            )
            if source_collision is not None or state_collision is not None:
                raise _config_error("Managed MCP Server ID conflicts after case folding.", server_id=server_id)
            managed = next(
                (raw for raw in snapshot.servers if raw.server_id == server_id and raw.source == "managed"),
                None,
            )
            if managed is None and len(snapshot.servers) >= _MAX_SERVERS:
                raise _config_error(f"At most {_MAX_SERVERS} MCP servers may be configured.")

            old_disabled = server_id in snapshot.disabled
            new_disabled = set(snapshot.disabled)
            if managed is None:
                new_disabled.discard(server_id)
            self._set_transaction(
                root,
                server_id=server_id,
                content=content,
                old_fragment=managed is not None,
                old_disabled=old_disabled,
                new_disabled=new_disabled,
            )
            enabled = server_id not in new_disabled
            return McpInventoryItem(
                server_id=server_id,
                source="managed",
                enabled=enabled,
                status="valid" if enabled else "disabled",
            )

    def set_enabled(self, server_id: str, enabled: bool) -> McpInventoryItem:
        _validate_server_id(server_id)
        if self._agent_root(create=False) is None:
            raise _config_error("Server does not exist.", server_id=server_id)
        with self._locked(create=True) as root:
            assert root is not None
            snapshot = self._read_snapshot(root)
            raw = next((item for item in snapshot.servers if item.server_id == server_id), None)
            if raw is None:
                raise _config_error("Server does not exist.", server_id=server_id)
            if any(
                item.server_id != server_id and item.server_id.casefold() == server_id.casefold()
                for item in snapshot.servers
            ):
                raise _config_error("Server ID is ambiguous after case folding.", server_id=server_id)
            if enabled:
                config = self._parse_servers((raw,))[0]
                self._validate_environment(config)
            disabled = set(snapshot.disabled)
            if enabled:
                disabled.discard(server_id)
            else:
                disabled.add(server_id)
            self._write_state(root, disabled)
            return McpInventoryItem(
                server_id=server_id,
                source=raw.source,
                enabled=enabled,
                status="valid" if enabled else "disabled",
            )

    def remove_server(self, server_id: str) -> None:
        _validate_server_id(server_id)
        if self._agent_root(create=False) is None:
            return
        with self._locked(create=True) as root:
            assert root is not None
            snapshot = self._read_snapshot(root)
            manual = any(raw.server_id == server_id and raw.source == "manual" for raw in snapshot.servers)
            managed = any(raw.server_id == server_id and raw.source == "managed" for raw in snapshot.servers)
            orphan = server_id in snapshot.disabled and not any(raw.server_id == server_id for raw in snapshot.servers)
            if manual and not managed:
                raise _config_error("A manual Server cannot be removed by this command.", server_id=server_id)
            if not managed and not orphan:
                return
            new_disabled = set(snapshot.disabled) - {server_id}
            if not managed:
                self._write_state(root, new_disabled)
                return
            self._remove_transaction(
                root,
                server_id=server_id,
                old_fragment=managed,
                old_disabled=server_id in snapshot.disabled,
                new_disabled=new_disabled,
            )

    @contextmanager
    def _locked(self, *, create: bool = False) -> Iterator[Path | None]:
        root = self._agent_root(create=create)
        if root is None:
            yield None
            return
        if _is_link_or_reparse(root):
            if not create and self._is_legacy_manual_only(root):
                yield root
                return
            raise _config_error("Managed MCP storage must not use a link or reparse point.")
        with _store_lock(root):
            self._recover(root)
            yield root

    def _agent_root(self, *, create: bool) -> Path | None:
        root = self._home / ".agent"
        if _is_within(root, self._workspace):
            raise _config_error("User MCP storage must not resolve inside the workspace.")
        if _lexists(root):
            if _has_windows_device_prefix(self._raw_home) and not (
                not create and _is_link_or_reparse(root) and self._is_legacy_manual_only(root)
            ):
                raise _config_error("Managed MCP storage must not use a device path.")
            if not _is_link_or_reparse(root) and not root.is_dir():
                raise _config_error("User Agent storage must be a directory.")
            return root
        if not create:
            return None
        if _has_windows_device_prefix(self._raw_home):
            raise _config_error("Managed MCP storage must not use a device path.")
        try:
            self._home.mkdir(parents=True, exist_ok=True)
            root.mkdir(mode=0o700)
        except OSError as exc:
            raise _config_error("Could not create managed MCP storage.") from exc
        _require_real_directory(root, message="Managed MCP storage must be a real directory.")
        return root

    def _is_legacy_manual_only(self, root: Path) -> bool:
        return _lexists(root / "mcp.toml") and not any(
            _lexists(root / name)
            for name in ("mcp.d", "mcp-state.json", ".extension.lock", ".extension-transactions")
        )

    def _read_snapshot(self, root: Path | None) -> _StoreSnapshot:
        if root is None:
            return _StoreSnapshot(servers=(), disabled=frozenset())
        disabled = self._read_state(root)
        manual = self._read_manual(root)
        managed = self._read_managed(root)
        manual_ids = {raw.server_id for raw in manual}
        duplicate = next((raw.server_id for raw in managed if raw.server_id in manual_ids), None)
        if duplicate is not None:
            raise _config_error("Server ID exists in both manual and managed configuration.", server_id=duplicate)
        servers = (*manual, *managed)
        if len(servers) > _MAX_SERVERS:
            raise _config_error(f"At most {_MAX_SERVERS} MCP servers may be configured.")
        exact_ids = {raw.server_id for raw in servers}
        folded_ids: dict[str, str] = {}
        for source_id in exact_ids:
            folded = source_id.casefold()
            previous = folded_ids.setdefault(folded, source_id)
            if source_id != previous and (source_id in disabled or previous in disabled):
                raise _config_error("MCP state has an ambiguous case-folded Server ID.")
        for disabled_id in disabled:
            match = folded_ids.get(disabled_id.casefold())
            if match is None:
                _validate_managed_id(disabled_id, state=True)
            elif match != disabled_id:
                raise _config_error("MCP state Server ID casing does not match its source.", server_id=disabled_id)
        return _StoreSnapshot(servers=tuple(servers), disabled=disabled)

    def _read_manual(self, root: Path) -> tuple[_RawServer, ...]:
        config_path = root / "mcp.toml"
        if not _lexists(config_path):
            return ()
        resolved_config, config_dir = _resolve_config_path(config_path, self._workspace)
        values = _read_toml(resolved_config, label="user MCP configuration")
        unknown_root_fields = set(values) - {"servers"}
        if unknown_root_fields:
            names = ", ".join(sorted(unknown_root_fields))
            raise _config_error(f"Unknown top-level field(s): {names}.")
        servers = values.get("servers", {})
        if not isinstance(servers, dict):
            raise _config_error("The 'servers' field must be a TOML table.")
        return tuple(
            _RawServer(server_id=server_id, source="manual", values=server_values, config_dir=config_dir)
            for server_id, server_values in servers.items()
        )

    def _read_managed(self, root: Path) -> tuple[_RawServer, ...]:
        fragments = root / "mcp.d"
        if not _lexists(fragments):
            return ()
        _require_real_directory(
            fragments,
            message="Managed MCP fragment storage must not use a link or reparse point.",
        )
        try:
            entries = tuple(fragments.iterdir())
        except OSError as exc:
            raise _config_error("Could not enumerate managed MCP fragments.") from exc
        result: list[_RawServer] = []
        folded: dict[str, str] = {}
        for path in entries:
            if _is_link_or_reparse(path):
                raise _config_error("Managed MCP fragments must not use links or reparse points.")
            if path.suffix != ".toml":
                if path.is_dir() or not path.is_file():
                    raise _config_error("Managed MCP fragment storage contains an unsupported entry.")
                continue
            _require_plain_file(path, message="Managed MCP fragment must be a regular file.")
            server_id = path.stem
            _validate_managed_id(server_id)
            previous = folded.setdefault(server_id.casefold(), server_id)
            if previous != server_id:
                raise _config_error("Managed MCP fragment IDs conflict after case folding.")
            values = _read_toml(path, label="managed MCP fragment")
            result.append(
                _RawServer(server_id=server_id, source="managed", values=values, config_dir=fragments)
            )
        return tuple(sorted(result, key=lambda raw: (raw.server_id.casefold(), raw.server_id)))

    def _read_state(self, root: Path) -> frozenset[str]:
        path = root / "mcp-state.json"
        if not _lexists(path):
            return frozenset()
        _require_plain_file(path, message="MCP state must be a regular file, not a link or reparse point.")
        try:
            if path.stat().st_size > _MAX_STATE_BYTES:
                raise _config_error("MCP state is too large.")
            values = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _config_error("Could not parse MCP state.") from exc
        except OSError as exc:
            raise _config_error("Could not read MCP state.") from exc
        if not isinstance(values, dict) or set(values) != _STATE_FIELDS:
            raise _config_error("MCP state has unknown or missing fields.")
        if type(values.get("version")) is not int or values["version"] != 1:
            raise _config_error("MCP state version is unsupported.")
        disabled = values.get("disabled")
        if not isinstance(disabled, list) or any(not isinstance(item, str) for item in disabled):
            raise _config_error("MCP state disabled field must be an array of Server IDs.")
        seen: set[str] = set()
        for server_id in disabled:
            _validate_server_id(server_id, state=True)
            folded = server_id.casefold()
            if folded in seen:
                raise _config_error("MCP state contains duplicate Server IDs.")
            seen.add(folded)
        return frozenset(disabled)

    def _inventory(self, snapshot: _StoreSnapshot) -> tuple[McpInventoryItem, ...]:
        items: list[McpInventoryItem] = []
        path_entries, path_extensions, subprocess_path, subprocess_pathext = self._path_context()
        for raw in snapshot.servers:
            enabled = raw.server_id not in snapshot.disabled
            try:
                _validate_server_shape(raw)
                if enabled:
                    config = _parse_server_config(
                        raw,
                        workspace=self._workspace,
                        path_entries=path_entries,
                        path_extensions=path_extensions,
                        subprocess_path=subprocess_path,
                        subprocess_pathext=subprocess_pathext,
                    )
                    if not path_entries:
                        raise _config_error(
                            "Sanitized PATH must contain at least one absolute directory outside the workspace."
                        )
                    self._validate_environment(config)
            except McpRuntimeError as exc:
                items.append(
                    McpInventoryItem(
                        server_id=raw.server_id,
                        source=raw.source,
                        enabled=enabled,
                        status="invalid",
                        message=exc.message[:512],
                    )
                )
            else:
                items.append(
                    McpInventoryItem(
                        server_id=raw.server_id,
                        source=raw.source,
                        enabled=enabled,
                        status="valid" if enabled else "disabled",
                    )
                )
        source_ids = {raw.server_id for raw in snapshot.servers}
        items.extend(
            McpInventoryItem(server_id=server_id, source="orphan", enabled=False, status="orphan")
            for server_id in sorted(snapshot.disabled - source_ids, key=lambda value: (value.casefold(), value))
        )
        return tuple(items)

    def _parse_servers(self, servers: tuple[_RawServer, ...]) -> tuple[McpServerConfig, ...]:
        if not servers:
            return ()
        path_entries, path_extensions, subprocess_path, subprocess_pathext = self._path_context()
        configs = tuple(
            _parse_server_config(
                raw,
                workspace=self._workspace,
                path_entries=path_entries,
                path_extensions=path_extensions,
                subprocess_path=subprocess_path,
                subprocess_pathext=subprocess_pathext,
            )
            for raw in servers
        )
        if not path_entries:
            raise _config_error("Sanitized PATH must contain at least one absolute directory outside the workspace.")
        return configs

    def _path_context(self) -> tuple[tuple[Path, ...], tuple[str, ...], str, str | None]:
        path_value = _STARTUP_PATH if self._environ is None else (_environment_value(self._environ, "PATH") or "")
        pathext_value = _STARTUP_PATHEXT if self._environ is None else _environment_value(self._environ, "PATHEXT")
        path_entries = _canonical_path_entries(path_value, self._workspace)
        path_extensions = _windows_path_extensions(pathext_value)
        return (
            path_entries,
            path_extensions,
            os.pathsep.join(str(path) for path in path_entries),
            ";".join(path_extensions) if os.name == "nt" else None,
        )

    def _validate_environment(self, config: McpServerConfig) -> None:
        environment: Mapping[str, str] = os.environ if self._environ is None else self._environ
        for name in config.pass_env:
            if _environment_value(environment, name) is None:
                raise _config_error(f"Required pass_env variable {name!r} is missing.", server_id=config.server_id)

    def _fragments_dir(self, root: Path, *, create: bool) -> Path:
        path = root / "mcp.d"
        if _lexists(path):
            _require_real_directory(path, message="Managed MCP fragment storage must be a real directory.")
            return path
        if create:
            try:
                path.mkdir(mode=0o700)
            except OSError as exc:
                raise _config_error("Could not create managed MCP fragment storage.") from exc
            _sync_directory(root)
        return path

    def _write_state(self, root: Path, disabled: set[str]) -> None:
        ordered = sorted(disabled, key=lambda value: (value.casefold(), value))
        _atomic_replace_json(root, root / "mcp-state.json", {"version": 1, "disabled": ordered})

    def _recover(self, root: Path) -> None:
        self._clean_owned_temps(root)
        transactions = root / ".extension-transactions"
        if not _lexists(transactions):
            return
        _require_real_directory(transactions, message="Extension transaction storage must be a real directory.")
        try:
            owned = tuple(
                path for path in transactions.iterdir() if path.name.startswith("mcp-")
            )
        except OSError as exc:
            raise _config_error("Could not enumerate MCP transactions.") from exc
        if len(owned) > 1:
            raise _config_error("Multiple MCP transactions require manual recovery.")
        if owned:
            tx = owned[0]
            if not _lexists(tx / "record.json"):
                try:
                    entries = tuple(tx.iterdir())
                except OSError as exc:
                    raise _config_error("Could not inspect unprepared MCP transaction.") from exc
                if any(path.name == "backup.toml" for path in entries):
                    raise _config_error("Unprepared MCP transaction contains a backup and requires manual recovery.")
                self._cleanup_transaction(root, tx, allow_missing_record=True)
            else:
                self._recover_transaction(root, tx)

    def _clean_owned_temps(self, root: Path) -> None:
        try:
            entries = tuple(root.iterdir())
        except OSError as exc:
            raise _config_error("Could not inspect managed MCP temporary files.") from exc
        for path in entries:
            if not _is_owned_temp_name(path.name, "mcp-state.json"):
                continue
            _require_plain_file(path, message="Managed MCP temporary path is unsafe.")
            try:
                path.unlink()
            except OSError as exc:
                raise _config_error("Could not clean managed MCP temporary file.") from exc

    def _set_transaction(
        self,
        root: Path,
        *,
        server_id: str,
        content: bytes,
        old_fragment: bool,
        old_disabled: bool,
        new_disabled: set[str],
    ) -> None:
        tx = self._prepare_transaction(
            root,
            operation="set",
            server_id=server_id,
            old_fragment=old_fragment,
            old_disabled=old_disabled,
            candidate=content,
        )
        target = self._fragments_dir(root, create=True) / f"{server_id}.toml"
        backup = tx / "backup.toml"
        candidate = tx / "candidate.toml"
        try:
            if old_fragment:
                _require_plain_file(target, message="Managed MCP fragment must be a regular file.")
                os.replace(target, backup)
            os.replace(candidate, target)
            _sync_directory(target.parent)
            self._write_state(root, new_disabled)
            self._write_transaction_phase(root, tx, "committed")
            self._cleanup_transaction(root, tx)
        except BaseException as exc:
            self._rollback_after_error(root, tx, exc)

    def _remove_transaction(
        self,
        root: Path,
        *,
        server_id: str,
        old_fragment: bool,
        old_disabled: bool,
        new_disabled: set[str],
    ) -> None:
        tx = self._prepare_transaction(
            root,
            operation="remove",
            server_id=server_id,
            old_fragment=old_fragment,
            old_disabled=old_disabled,
            candidate=None,
        )
        target = self._fragments_dir(root, create=False) / f"{server_id}.toml"
        backup = tx / "backup.toml"
        try:
            if old_fragment:
                _require_plain_file(target, message="Managed MCP fragment must be a regular file.")
                os.replace(target, backup)
                _sync_directory(target.parent)
            self._write_state(root, new_disabled)
            self._write_transaction_phase(root, tx, "committed")
            self._cleanup_transaction(root, tx)
        except BaseException as exc:
            self._rollback_after_error(root, tx, exc)

    def _prepare_transaction(
        self,
        root: Path,
        *,
        operation: Literal["set", "remove"],
        server_id: str,
        old_fragment: bool,
        old_disabled: bool,
        candidate: bytes | None,
    ) -> Path:
        transactions = root / ".extension-transactions"
        if _lexists(transactions):
            _require_real_directory(transactions, message="Extension transaction storage must be a real directory.")
        else:
            try:
                transactions.mkdir(mode=0o700)
            except OSError as exc:
                raise _config_error("Could not create MCP transaction storage.") from exc
            _sync_directory(root)
        tx = transactions / f"mcp-{uuid.uuid4().hex}"
        created_tx = False
        try:
            tx.mkdir(mode=0o700)
            created_tx = True
            _write_new_file(tx / _TRANSACTION_OWNER_NAME, _TRANSACTION_OWNER)
            _sync_directory(tx)
            _sync_directory(transactions)
            if candidate is not None:
                _write_new_file(tx / "candidate.toml", candidate)
            record = {
                "version": 1,
                "module": "mcp",
                "operation": operation,
                "server_id": server_id,
                "old_disabled": old_disabled,
                "old_fragment": old_fragment,
                "phase": "prepared",
            }
            _atomic_replace_json(root, tx / "record.json", record)
            _sync_directory(tx)
            return tx
        except BaseException as exc:
            try:
                if created_tx and _lexists(tx):
                    self._cleanup_transaction(root, tx, allow_missing_record=True, trusted_new=True)
            except McpRuntimeError:
                pass
            if isinstance(exc, McpRuntimeError):
                raise
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise _config_error("Could not prepare MCP transaction.") from exc

    def _write_transaction_phase(self, root: Path, tx: Path, phase: Literal["prepared", "committed"]) -> None:
        record = self._read_transaction(tx)
        record["phase"] = phase
        _atomic_replace_json(root, tx / "record.json", record)

    def _rollback_after_error(self, root: Path, tx: Path, exc: BaseException) -> None:
        try:
            self._recover_transaction(root, tx)
        except McpRuntimeError as recovery_error:
            raise recovery_error from exc
        if isinstance(exc, McpRuntimeError):
            raise exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise exc
        raise _config_error("Could not write managed MCP state.") from exc

    def _recover_transaction(self, root: Path, tx: Path) -> None:
        self._transaction_entries(tx, require_owner=True)
        record = self._read_transaction(tx)
        server_id = record["server_id"]
        operation = record["operation"]
        target = self._fragments_dir(root, create=False) / f"{server_id}.toml"
        candidate = tx / "candidate.toml"
        backup = tx / "backup.toml"
        if _lexists(candidate):
            _require_plain_file(candidate, message="MCP transaction candidate must be a regular file.")
        if _lexists(backup):
            _require_plain_file(backup, message="MCP transaction backup must be a regular file.")
        if _lexists(target):
            _require_plain_file(target, message="Managed MCP fragment must be a regular file.")

        if record["phase"] == "prepared":
            if record["old_fragment"]:
                if _lexists(backup):
                    fragments = self._fragments_dir(root, create=True)
                    target = fragments / f"{server_id}.toml"
                    try:
                        old_content = backup.read_bytes()
                    except OSError as exc:
                        raise _config_error("Could not read the MCP transaction backup.", server_id=server_id) from exc
                    _atomic_replace_bytes(root, target, old_content)
                elif not (
                    _lexists(target)
                    and (operation == "remove" or _lexists(candidate))
                ):
                    raise _config_error("MCP transaction backup is missing.", server_id=server_id)
            elif _lexists(target):
                target.unlink()
            disabled = set(self._read_state(root))
            if record["old_disabled"]:
                disabled.add(server_id)
            else:
                disabled.discard(server_id)
            self._write_state(root, disabled)
        else:
            disabled = self._read_state(root)
            if operation == "set":
                if not _lexists(target):
                    raise _config_error("Committed MCP fragment is missing.", server_id=server_id)
                _require_plain_file(target, message="Committed MCP fragment must be a regular file.")
                expected_disabled = record["old_disabled"] if record["old_fragment"] else False
                if (server_id in disabled) != expected_disabled:
                    raise _config_error("Committed MCP state does not match its fragment.", server_id=server_id)
                _validate_server_shape(
                    _RawServer(server_id=server_id, source="managed", values=_read_toml(target, label="managed MCP fragment"), config_dir=target.parent)
                )
            elif _lexists(target) or server_id in disabled:
                raise _config_error("Committed MCP removal is incomplete.", server_id=server_id)
        self._cleanup_transaction(root, tx)

    def _read_transaction(self, tx: Path) -> dict[str, Any]:
        path = tx / "record.json"
        _require_plain_file(path, message="MCP transaction record must be a regular file.")
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _config_error("Could not parse MCP transaction record.") from exc
        if not isinstance(values, dict) or set(values) != _TRANSACTION_FIELDS:
            raise _config_error("MCP transaction record has unknown or missing fields.")
        if type(values.get("version")) is not int or values.get("version") != 1 or values.get("module") != "mcp":
            raise _config_error("MCP transaction record version or module is invalid.")
        if values.get("operation") not in {"set", "remove"} or values.get("phase") not in {"prepared", "committed"}:
            raise _config_error("MCP transaction record operation or phase is invalid.")
        if type(values.get("old_disabled")) is not bool or type(values.get("old_fragment")) is not bool:
            raise _config_error("MCP transaction record state is invalid.")
        _validate_managed_id(values.get("server_id"))
        return values

    def _transaction_entries(self, tx: Path, *, require_owner: bool) -> tuple[Path, ...]:
        _require_real_directory(tx, message="MCP transaction must be a real directory.")
        if _TRANSACTION_NAME_PATTERN.fullmatch(tx.name) is None:
            raise _config_error("MCP transaction name is not trustworthy.")
        allowed = {_TRANSACTION_OWNER_NAME, "record.json", "candidate.toml", "backup.toml"}
        try:
            entries = tuple(tx.iterdir())
        except OSError as exc:
            raise _config_error("Could not enumerate MCP transaction files.") from exc
        if any(
            (path.name not in allowed and not _is_owned_temp_name(path.name, "record.json"))
            or _is_link_or_reparse(path)
            or not path.is_file()
            for path in entries
        ):
            raise _config_error("MCP transaction contains an unknown or unsafe entry.")
        if require_owner:
            owner = tx / _TRANSACTION_OWNER_NAME
            if not _lexists(owner):
                raise _config_error("Unprepared MCP transaction has no trustworthy ownership marker.")
            _require_plain_file(owner, message="MCP transaction ownership marker must be a regular file.")
            try:
                owned = owner.stat().st_size == len(_TRANSACTION_OWNER) and owner.read_bytes() == _TRANSACTION_OWNER
            except OSError as exc:
                raise _config_error("Could not read MCP transaction ownership marker.") from exc
            if not owned:
                raise _config_error("MCP transaction has no trustworthy ownership marker.")
        return entries

    def _cleanup_transaction(
        self,
        root: Path,
        tx: Path,
        *,
        allow_missing_record: bool = False,
        trusted_new: bool = False,
    ) -> None:
        entries = self._transaction_entries(tx, require_owner=not trusted_new)
        if not allow_missing_record and not any(path.name == "record.json" for path in entries):
            raise _config_error("MCP transaction record is missing.")
        try:
            for path in entries:
                path.unlink()
            tx.rmdir()
            transactions = tx.parent
            if not any(transactions.iterdir()):
                transactions.rmdir()
            _sync_directory(root)
        except OSError as exc:
            raise _config_error("Could not clean MCP transaction.") from exc


def load_mcp_server_configs(
    workspace: Path,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[McpServerConfig, ...]:
    return McpConfigStore(workspace, home=home, environ=environ).load_enabled_configs()


@contextmanager
def _store_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".extension.lock"
    if _lexists(lock_path):
        _require_plain_file(lock_path, message="Extension lock must be a regular file, not a link or reparse point.")
    try:
        handle = lock_path.open("a+b", buffering=0)
    except OSError as exc:
        raise _config_error("Could not open the extension lock.") from exc
    acquired = False
    try:
        _require_plain_file(lock_path, message="Extension lock must remain a regular file.")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            os.fsync(handle.fileno())
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            handle.seek(0)
            try:
                _lock_file(handle)
                acquired = True
                break
            except OSError as exc:
                if not _lock_would_block(exc):
                    raise _config_error("Could not acquire the extension lock.") from exc
                if time.monotonic() >= deadline:
                    raise _config_error("Managed MCP storage is busy.") from exc
                time.sleep(min(_LOCK_RETRY_SECONDS, max(0.0, deadline - time.monotonic())))
        _require_plain_file(lock_path, message="Extension lock must remain a regular file.")
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                _unlock_file(handle)
            except OSError:
                pass
        handle.close()


def _lock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_would_block(exc: OSError) -> bool:
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


def _atomic_replace_json(root: Path, target: Path, value: Any) -> None:
    encoded = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if json.loads(encoded) != value:
        raise _config_error("Could not verify serialized MCP state.")
    if target.name == "mcp-state.json" and len(encoded) > _MAX_STATE_BYTES:
        raise _config_error("MCP state is too large.")
    _atomic_replace_bytes(root, target, encoded)


def _atomic_replace_bytes(root: Path, target: Path, data: bytes) -> None:
    _require_store_path(root, target)
    _require_real_directory(target.parent, message="Managed MCP target parent must be a real directory.")
    if _lexists(target):
        _require_plain_file(target, message="Managed MCP target must be a regular file.")
    descriptor = -1
    temp_path: Path | None = None
    try:
        temp_path = target.parent / f".{target.name}.agent-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _require_plain_file(temp_path, message="Managed MCP temporary file must be a regular file.")
        if _lexists(target):
            _require_plain_file(target, message="Managed MCP target must remain a regular file.")
        os.replace(temp_path, target)
        temp_path = None
        _sync_directory(target.parent)
    except McpRuntimeError:
        raise
    except OSError as exc:
        raise _config_error("Could not write managed MCP state.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _write_new_file(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise _config_error("Could not write MCP transaction candidate.") from exc
    _require_plain_file(path, message="MCP transaction candidate must be a regular file.")


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if _directory_sync_is_unsupported(exc):
            return
        raise _config_error("Could not open managed MCP directory for synchronization.") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if not _directory_sync_is_unsupported(exc):
            raise _config_error("Could not synchronize managed MCP directory.") from exc
    finally:
        os.close(descriptor)


def _directory_sync_is_unsupported(exc: OSError) -> bool:
    return exc.errno in {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }


def _serialize_fragment(values: dict[str, Any], *, server_id: str) -> bytes:
    lines = [f"command = {json.dumps(values['command'])}"]
    for field in ("args", "pass_env"):
        rendered = ", ".join(json.dumps(item) for item in values[field])
        lines.append(f"{field} = [{rendered}]")
    lines.append(f"cwd = {json.dumps(values['cwd'])}")
    encoded = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        decoded = tomllib.loads(encoded.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise _config_error("Could not serialize managed MCP fragment.", server_id=server_id) from exc
    if decoded != values:
        raise _config_error("Could not verify managed MCP fragment.", server_id=server_id)
    return encoded


def _is_owned_temp_name(name: str, target_name: str) -> bool:
    prefix = f".{target_name}.agent-"
    return name.startswith(prefix) and _TEMP_NAME_PATTERN.fullmatch(name[len(prefix) :]) is not None


def _validate_server_shape(raw: _RawServer) -> None:
    if raw.source == "managed":
        _validate_managed_id(raw.server_id)
    else:
        _validate_server_id(raw.server_id)
    if not isinstance(raw.values, dict):
        raise _config_error("Server configuration must be a TOML table.", server_id=raw.server_id)
    unknown_fields = set(raw.values) - _SERVER_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise _config_error(f"Unknown server field(s): {names}.", server_id=raw.server_id)


def _parse_server_config(
    raw: _RawServer,
    *,
    workspace: Path,
    path_entries: tuple[Path, ...],
    path_extensions: tuple[str, ...],
    subprocess_path: str,
    subprocess_pathext: str | None,
) -> McpServerConfig:
    _validate_server_shape(raw)
    values = raw.values
    command = values.get("command")
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise _config_error("'command' must be a non-empty string.", server_id=raw.server_id)
    args = _string_list(values.get("args", []), field="args", server_id=raw.server_id)
    pass_env = _pass_env_names(values.get("pass_env", []), server_id=raw.server_id)
    cwd_mode = values.get("cwd", "config")
    if not isinstance(cwd_mode, str) or cwd_mode not in {"config", "workspace"}:
        raise _config_error("'cwd' must be either 'config' or 'workspace'.", server_id=raw.server_id)
    resolved_command = _resolve_command(
        command,
        workspace=workspace,
        path_entries=path_entries,
        path_extensions=path_extensions,
        server_id=raw.server_id,
    )
    expanded_args = tuple(str(workspace) if value == "{workspace}" else value for value in args)
    return McpServerConfig(
        server_id=raw.server_id,
        command=resolved_command,
        args=expanded_args,
        pass_env=pass_env,
        cwd=raw.config_dir if cwd_mode == "config" else workspace,
        subprocess_path=subprocess_path,
        subprocess_pathext=subprocess_pathext,
    )


def _validate_server_id(value: Any, *, state: bool = False) -> str:
    if not isinstance(value, str) or _SERVER_ID_PATTERN.fullmatch(value) is None:
        label = "MCP state Server ID" if state else "Server ID"
        raise _config_error(f"{label} must contain only ASCII letters, digits, '_' or '-'.")
    return value


def _validate_managed_id(value: Any, *, state: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or _SERVER_ID_PATTERN.fullmatch(value) is None
        or value.upper() in _WINDOWS_RESERVED_NAMES
    ):
        label = "MCP state Server ID" if state else "Managed MCP Server ID"
        raise _config_error(f"{label} is not a safe 1-64 character identifier.")
    return value


def _string_list(value: Any, *, field: str, server_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _config_error(f"'{field}' must be an array of strings.", server_id=server_id)
    if any("\x00" in item for item in value):
        raise _config_error(f"'{field}' must not contain NUL characters.", server_id=server_id)
    return tuple(value)


def _pass_env_names(value: Any, *, server_id: str) -> tuple[str, ...]:
    names = _string_list(value, field="pass_env", server_id=server_id)
    seen: set[str] = set()
    reserved = {item.casefold() if os.name == "nt" else item for item in ("PATH", "PATHEXT")}
    for name in names:
        if _ENV_NAME_PATTERN.fullmatch(name) is None:
            raise _config_error(f"Invalid pass_env variable name: {name!r}.", server_id=server_id)
        comparison = name.casefold() if os.name == "nt" else name
        if comparison in reserved:
            raise _config_error(f"pass_env variable {name!r} is reserved.", server_id=server_id)
        if comparison in seen:
            raise _config_error(f"Duplicate pass_env variable: {name!r}.", server_id=server_id)
        seen.add(comparison)
    return names


def _resolve_command(
    command: str,
    *,
    workspace: Path,
    path_entries: tuple[Path, ...],
    path_extensions: tuple[str, ...],
    server_id: str,
) -> Path:
    command_path = Path(command)
    if command_path.is_absolute():
        try:
            resolved = command_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _config_error("Absolute command must resolve to an existing file.", server_id=server_id) from exc
        if not resolved.is_file():
            raise _config_error("Absolute command must resolve to an existing file.", server_id=server_id)
        _require_native_windows_command(resolved, server_id=server_id)
        return resolved
    if _has_path_syntax(command):
        raise _config_error("Relative command paths are not allowed.", server_id=server_id)
    candidate_names = _command_candidate_names(command, path_extensions, server_id=server_id)
    for directory in path_entries:
        for candidate_name in candidate_names:
            candidate = directory / candidate_name
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not resolved.is_file() or _is_within(resolved, workspace) or not _is_native_windows_command(resolved):
                continue
            if os.name != "nt" and not os.access(resolved, os.X_OK):
                continue
            return resolved
    raise _config_error(f"Bare command {command!r} was not found in the sanitized PATH.", server_id=server_id)


def _has_path_syntax(command: str) -> bool:
    windows_path = PureWindowsPath(command)
    return command in {".", ".."} or "/" in command or "\\" in command or bool(windows_path.drive or windows_path.root)


def _command_candidate_names(command: str, path_extensions: tuple[str, ...], *, server_id: str) -> tuple[str, ...]:
    if os.name != "nt":
        return (command,)
    suffix = PureWindowsPath(command).suffix.upper()
    if suffix:
        if suffix not in _WINDOWS_NATIVE_EXTENSIONS:
            raise _config_error("Windows command must be a native executable (.exe or .com).", server_id=server_id)
        return (command,)
    return tuple(f"{command}{extension.lower()}" for extension in path_extensions)


def _require_native_windows_command(path: Path, *, server_id: str) -> None:
    if not _is_native_windows_command(path):
        raise _config_error("Windows command must be a native executable (.exe or .com).", server_id=server_id)


def _is_native_windows_command(path: Path) -> bool:
    return os.name != "nt" or path.suffix.upper() in _WINDOWS_NATIVE_EXTENSIONS


def _canonical_path_entries(value: str, workspace: Path) -> tuple[Path, ...]:
    entries: list[Path] = []
    seen: set[str] = set()
    for raw_entry in value.split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        if not entry.is_absolute():
            continue
        try:
            resolved = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir() or os.pathsep in str(resolved) or _is_within(resolved, workspace):
            continue
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        entries.append(resolved)
    return tuple(entries)


def _windows_path_extensions(value: str | None) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    extensions: list[str] = []
    seen: set[str] = set()
    for raw_extension in (value or "").split(";"):
        extension = raw_extension.strip().upper()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        if extension not in _WINDOWS_NATIVE_EXTENSIONS or extension in seen:
            continue
        seen.add(extension)
        extensions.append(extension)
    return tuple(extensions)


def _environment_value(environ: Mapping[str, str], name: str) -> str | None:
    if os.name != "nt":
        return environ.get(name)
    folded_name = name.casefold()
    return next((value for key, value in environ.items() if key.casefold() == folded_name), None)


def _resolve_workspace(workspace: Path) -> Path:
    try:
        resolved = workspace.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _config_error("Workspace does not exist or cannot be resolved.") from exc
    if not resolved.is_dir():
        raise _config_error("Workspace must be a directory.")
    return resolved


def _resolve_config_path(config_path: Path, workspace: Path) -> tuple[Path, Path]:
    try:
        config_dir = config_path.parent.resolve(strict=True)
        resolved_config = config_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _config_error("User MCP configuration cannot be resolved.") from exc
    if _is_within(config_dir, workspace) or _is_within(resolved_config, workspace):
        raise _config_error("User MCP configuration must not resolve inside the workspace.")
    if not resolved_config.is_file():
        raise _config_error("User MCP configuration must be a file.")
    return resolved_config, config_dir


def _read_toml(path: Path, *, label: str) -> dict[str, Any]:
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise _config_error(f"Could not parse {label}.") from exc
    except OSError as exc:
        raise _config_error(f"Could not read {label}.") from exc
    return values


def _require_store_path(root: Path, path: Path) -> None:
    if not _is_within(path.parent, root) or _has_windows_device_prefix(path):
        raise _config_error("Managed MCP path escapes its storage root.")
    current = root
    relative = path.relative_to(root)
    for part in relative.parts[:-1]:
        current /= part
        if _lexists(current) and _is_link_or_reparse(current):
            raise _config_error("Managed MCP path uses a link or reparse point.")


def _require_real_directory(path: Path, *, message: str) -> None:
    if _is_link_or_reparse(path) or not path.is_dir():
        raise _config_error(message)


def _require_plain_file(path: Path, *, message: str) -> None:
    if _is_link_or_reparse(path) or not path.is_file():
        raise _config_error(message)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return stat.S_ISLNK(details.st_mode) or bool(getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _has_windows_device_prefix(path: Path) -> bool:
    if os.name != "nt":
        return False
    value = str(path).replace("/", "\\")
    return value.startswith("\\\\?\\") or value.startswith("\\\\.\\")


def _is_within(path: Path, root: Path) -> bool:
    path_text = _comparison_path(path)
    root_text = _comparison_path(root)
    try:
        if os.path.commonpath([path_text, root_text]) == root_text:
            return True
    except ValueError:
        pass
    for candidate in (path, *path.parents):
        try:
            if candidate.samefile(root):
                return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def _comparison_path(path: Path) -> str:
    value = os.path.normcase(os.path.normpath(str(path)))
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\unc\\"):
        return f"\\\\{value[8:]}"
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _config_error(message: str, *, server_id: str | None = None) -> McpRuntimeError:
    return McpRuntimeError(stage="config", server_id=server_id, message=message)


__all__ = [
    "McpConfigStore",
    "McpInventoryItem",
    "McpRuntimeError",
    "McpServerConfig",
    "load_mcp_server_configs",
]
