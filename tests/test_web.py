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
