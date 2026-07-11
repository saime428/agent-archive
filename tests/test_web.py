from __future__ import annotations

from agent.web import server


def test_build_chat_events_payload_prunes_finished_jobs_after_ttl(monkeypatch, tmp_path) -> None:
    old = server._ChatJob(
        job_id="job_old",
        workspace=tmp_path,
        session_id="chat_old",
        message="old",
    )
    old.done = True
    old.completed_at = 100.0
    active = server._ChatJob(
        job_id="job_active",
        workspace=tmp_path,
        session_id="chat_active",
        message="active",
    )

    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()
        server._CHAT_JOBS[old.job_id] = old
        server._CHAT_JOBS[active.job_id] = active

    monkeypatch.setattr(server.time, "monotonic", lambda: 100.0 + server.CHAT_JOB_TTL_SECONDS + 1.0)

    payload = server.build_chat_events_payload(active.job_id, timeout=0)

    assert payload["job_id"] == active.job_id
    with server._CHAT_JOBS_LOCK:
        assert old.job_id not in server._CHAT_JOBS
        assert active.job_id in server._CHAT_JOBS
        server._CHAT_JOBS.clear()


def test_config_update_accepts_openai_compat_provider(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = server.build_save_config_payload(
        workspace,
        {
            "provider": "openai-compat",
            "model": "gpt-4o-mini",
            "sandbox": "workspace-write",
            "approval": "risky-confirm",
            "dry_run": True,
            "web_search_enabled": True,
            "computer_read_enabled": True,
            "default_skills": ["code-dev"],
        },
    )

    assert payload["status"] == "ok"
    assert payload["config"]["provider"] == "openai-compat"


def test_build_health_payload_reports_native_tools_disabled_by_default(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = server.build_health_payload(workspace)

    assert payload["native_tools"] is False


def test_config_update_accepts_native_tools_boolean(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    payload = server.build_save_config_payload(workspace, {"native_tools": True})

    assert payload["status"] == "ok"
    config_text = (workspace / ".agent" / "config.toml").read_text(encoding="utf-8")
    assert "native_tools = true" in config_text


def test_config_update_rejects_non_boolean_native_tools(tmp_path) -> None:
    import pytest

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError):
        server.build_save_config_payload(workspace, {"native_tools": "yes"})


def test_chat_job_streams_tagged_model_chunks(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")

    class StreamingFake:
        def chat_tools(self, messages, tools, *, temperature=None):
            raise AssertionError("streaming path expected when stream_handler is provided")

        def stream_chat_tools(self, messages, tools, *, temperature=None):
            yield ("thinking", "planning")
            yield ("args", '{"final"')
            return {
                "message": "",
                "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
            }

    monkeypatch.setattr(server, "make_llm", lambda config: StreamingFake())

    started = server.build_chat_start_payload(workspace, {"message": "hi"})
    events: list[dict] = []
    after = 0
    for _ in range(50):
        payload = server.build_chat_events_payload(started["job_id"], after=after, timeout=5.0)
        events.extend(payload["events"])
        after = payload["next"]
        if payload["done"]:
            break
    with server._CHAT_JOBS_LOCK:
        server._CHAT_JOBS.clear()

    chunk_events = [event for event in events if event.get("event") == "model_stream_chunk"]
    assert [(event["kind"], event["text"]) for event in chunk_events] == [
        ("thinking", "planning"),
        ("args", '{"final"'),
    ]
    assert any(event.get("event") == "final" for event in events)
