from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_user_home(tmp_path_factory, monkeypatch):
    """Keep every test off the developer's real ``~/.agent`` store.

    ``discover_skills`` and the MCP runtime resolve the user store through
    ``Path.home()``, so without this the suite would read whatever extensions
    the machine happens to have installed. Tests that need their own home
    still override these variables afterwards.
    """
    home = tmp_path_factory.mktemp("user-home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home
