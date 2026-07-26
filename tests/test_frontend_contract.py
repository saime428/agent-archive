from __future__ import annotations

import json
import re
from pathlib import Path

from agent.web.files import build_files_payload
from agent.web.runs import build_runs_payload
from agent.web.settings import build_config_payload, build_health_payload, build_tools_payload


ROOT = Path(__file__).resolve().parents[1]
_PAYLOAD_CONTRACT = json.loads(
    (ROOT / "frontend" / "src" / "test" / "workbench-payloads.json").read_text(encoding="utf-8")
)


def _required(name: str) -> list[str]:
    return _PAYLOAD_CONTRACT[name]["required"]


def test_frontend_event_catalog_matches_frontend_and_backend() -> None:
    fixture = json.loads((ROOT / "frontend" / "src" / "test" / "chat-events.json").read_text(encoding="utf-8"))
    known = fixture["known_events"]
    frontend_source = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    block = frontend_source.split("export const CHAT_EVENT_NAMES = [", 1)[1].split("] as const;", 1)[0]
    frontend = re.findall(r'"([a-z_]+)"', block)
    backend_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "src" / "agent" / "core" / "loop.py",
            ROOT / "src" / "agent" / "web" / "chat_runtime.py",
        )
    )

    assert known == frontend
    assert all(f'"{name}"' in backend_source for name in known)
    assert len(known) == 18


def test_approval_required_event_carries_expiry_window() -> None:
    fixture = json.loads((ROOT / "frontend" / "src" / "test" / "chat-events.json").read_text(encoding="utf-8"))
    backend_source = (ROOT / "src" / "agent" / "web" / "chat_runtime.py").read_text(encoding="utf-8")
    frontend_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert fixture["approval_required_extra_fields"] == ["expires_in_ms"]
    for field in fixture["approval_required_extra_fields"]:
        assert f'"{field}"' in backend_source, field
        assert field in frontend_source, field


def test_health_payload_carries_required_keys_and_read_only_sections(tmp_path) -> None:
    payload = build_health_payload(tmp_path)

    for key in _required("health"):
        assert key in payload, key
    for section in _PAYLOAD_CONTRACT["health"]["read_only_sections"]:
        assert payload[section]["mode"] == "read-only", section


def test_config_payload_contract(tmp_path) -> None:
    payload = build_config_payload(tmp_path)

    for key in _required("config"):
        assert key in payload, key
    for key in _PAYLOAD_CONTRACT["config"]["diagnostics_keys"]:
        assert key in payload["diagnostics"], key


def test_tools_payload_contract() -> None:
    payload = build_tools_payload()

    assert "tools" in payload
    assert payload["tools"], "expected at least one built-in tool"
    for key in _PAYLOAD_CONTRACT["tools"]["tool_keys"]:
        assert key in payload["tools"][0], key


def test_files_payload_contract(tmp_path) -> None:
    (tmp_path / "sample.txt").write_text("hi", encoding="utf-8")
    payload = build_files_payload(tmp_path)

    for key in _required("files"):
        assert key in payload, key
    assert payload["entries"], "expected the sample file to be listed"
    for key in _PAYLOAD_CONTRACT["files"]["entry_keys"]:
        assert key in payload["entries"][0], key


def test_runs_payload_contract(tmp_path) -> None:
    payload = build_runs_payload(tmp_path)

    for key in _required("runs"):
        assert key in payload, key
    assert isinstance(payload["runs"], list)
