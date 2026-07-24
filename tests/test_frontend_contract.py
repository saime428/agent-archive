from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_event_catalog_matches_legacy_and_backend() -> None:
    fixture = json.loads((ROOT / "frontend" / "src" / "test" / "chat-events.json").read_text(encoding="utf-8"))
    known = fixture["known_events"]
    legacy_source = (ROOT / "src" / "agent" / "web" / "static" / "assets" / "sse.js").read_text(encoding="utf-8")
    block = legacy_source.split("const CHAT_EVENT_NAMES = [", 1)[1].split("];", 1)[0]
    legacy = re.findall(r'"([a-z_]+)"', block)

    assert known == [*legacy[:-2], "capability_warning", *legacy[-2:]]
    assert '"capability_warning"' in (ROOT / "src" / "agent" / "core" / "loop.py").read_text(encoding="utf-8")
    assert len(known) == 14
