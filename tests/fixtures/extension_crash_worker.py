from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import agent.core.skills as skills_module
import agent.mcp_config as mcp_config
from agent.core.skills import SkillStore
from agent.mcp_config import McpConfigStore


_CRASH_EXIT = 91


def _install_skill_crash(crash_at: str) -> None:
    if crash_at == "candidate":
        real_copy = SkillStore._copy_candidate

        def copy_candidate(self, source, candidate, entries) -> None:
            real_copy(self, source, candidate, entries)
            os._exit(_CRASH_EXIT)

        SkillStore._copy_candidate = copy_candidate
        return

    if crash_at == "cleanup":
        real_cleanup = SkillStore._cleanup_transaction

        def cleanup(self, root, tx, *, allow_missing_record=False, trusted_new=False) -> None:
            real_cleanup(
                self,
                root,
                tx,
                allow_missing_record=allow_missing_record,
                trusted_new=trusted_new,
            )
            os._exit(_CRASH_EXIT)

        SkillStore._cleanup_transaction = cleanup
        return

    if crash_at == "prepared":
        real_write_record = SkillStore._write_record

        def write_record(self, root, tx, record) -> None:
            real_write_record(self, root, tx, record)
            if record.get("phase") == "prepared":
                os._exit(_CRASH_EXIT)

        SkillStore._write_record = write_record
        return

    if crash_at in {"backup", "target"}:
        real_replace = skills_module.os.replace

        def replace(source, target) -> None:
            real_replace(source, target)
            target_path = Path(target)
            if crash_at == "backup" and target_path.name == "backup":
                os._exit(_CRASH_EXIT)
            if crash_at == "target" and target_path.parent.name == "skills":
                os._exit(_CRASH_EXIT)

        skills_module.os.replace = replace
        return

    if crash_at == "state":
        real_write_state = SkillStore._write_state

        def write_state(self, root, disabled) -> None:
            real_write_state(self, root, disabled)
            os._exit(_CRASH_EXIT)

        SkillStore._write_state = write_state
        return

    if crash_at == "committed":
        real_write_phase = SkillStore._write_transaction_phase

        def write_phase(self, root, tx, phase) -> None:
            real_write_phase(self, root, tx, phase)
            if phase == "committed":
                os._exit(_CRASH_EXIT)

        SkillStore._write_transaction_phase = write_phase


def _install_crash(crash_at: str) -> None:
    if crash_at in {"candidate", "prepared"}:
        real_atomic_json = mcp_config._atomic_replace_json

        def atomic_json(root, target, value) -> None:
            if Path(target).name == "record.json" and value.get("phase") == "prepared":
                if crash_at == "candidate":
                    os._exit(_CRASH_EXIT)
                real_atomic_json(root, target, value)
                os._exit(_CRASH_EXIT)
            real_atomic_json(root, target, value)

        mcp_config._atomic_replace_json = atomic_json
        return

    if crash_at in {"backup", "target"}:
        real_replace = mcp_config.os.replace

        def replace(source, target) -> None:
            real_replace(source, target)
            target_path = Path(target)
            if crash_at == "backup" and target_path.name == "backup.toml":
                os._exit(_CRASH_EXIT)
            if crash_at == "target" and target_path.parent.name == "mcp.d":
                os._exit(_CRASH_EXIT)

        mcp_config.os.replace = replace
        return

    if crash_at == "state":
        real_write_state = McpConfigStore._write_state

        def write_state(self, root, disabled) -> None:
            real_write_state(self, root, disabled)
            os._exit(_CRASH_EXIT)

        McpConfigStore._write_state = write_state
        return

    if crash_at == "committed":
        real_write_phase = McpConfigStore._write_transaction_phase

        def write_phase(self, root, tx, phase) -> None:
            real_write_phase(self, root, tx, phase)
            if phase == "committed":
                os._exit(_CRASH_EXIT)

        McpConfigStore._write_transaction_phase = write_phase
        return

    if crash_at == "cleanup":
        real_cleanup = McpConfigStore._cleanup_transaction

        def cleanup(self, root, tx, *, allow_missing_record=False, trusted_new=False) -> None:
            real_cleanup(
                self,
                root,
                tx,
                allow_missing_record=allow_missing_record,
                trusted_new=trusted_new,
            )
            os._exit(_CRASH_EXIT)

        McpConfigStore._cleanup_transaction = cleanup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "hold-lock",
            "crash-set",
            "crash-remove",
            "crash-skill-install",
            "crash-skill-remove",
            "crash-skill-update",
        ),
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--skill", default="reviewer")
    parser.add_argument(
        "--crash-at",
        choices=("candidate", "prepared", "backup", "target", "state", "committed", "cleanup"),
    )
    args = parser.parse_args()

    if args.mode in {"crash-skill-install", "crash-skill-remove", "crash-skill-update"}:
        if args.crash_at is None:
            parser.error("--crash-at is required for skill crash modes")
        _install_skill_crash(args.crash_at)
        skill_store = SkillStore(args.workspace, home=args.home)
        if args.mode == "crash-skill-remove":
            skill_store.remove(args.skill)
        else:
            if args.source is None:
                parser.error("--source is required for skill install and update crash modes")
            if args.mode == "crash-skill-install":
                skill_store.install(args.source)
            else:
                skill_store.update(args.skill, args.source)
        raise AssertionError("crash injection did not terminate the process")

    environment = {"PATH": str(Path(sys.executable).resolve().parent), "PATHEXT": ".EXE;.COM"}
    store = McpConfigStore(args.workspace, home=args.home, environ=environment)
    if args.mode == "crash-set":
        if args.crash_at is None:
            parser.error("--crash-at is required for crash-set")
        _install_crash(args.crash_at)
        store.set_server(
            "alpha",
            command=str(Path(sys.executable).resolve()),
            args=("v2",),
            pass_env=(),
            cwd="config",
        )
        raise AssertionError("crash injection did not terminate the process")

    if args.mode == "crash-remove":
        if args.crash_at is None:
            parser.error("--crash-at is required for crash-remove")
        _install_crash(args.crash_at)
        store.remove_server("alpha")
        raise AssertionError("crash injection did not terminate the process")

    if args.ready is None:
        parser.error("--ready is required for hold-lock")
    with store._locked(create=True):
        args.ready.write_text("ready\n", encoding="utf-8")
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
