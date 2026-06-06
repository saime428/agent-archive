from agent.llm.fake import FakeLLMClient


def test_fake_llm_returns_done_action_with_task() -> None:
    client = FakeLLMClient()

    response = client.chat([{"role": "user", "content": "inspect project"}])

    assert response["message"] == "Task completed by FakeLLM."
    assert response["action"]["name"] == "done"
    assert response["action"]["args"]["final"] == "FakeLLM received task: inspect project"
    assert response["action"]["args"]["changed_files"] == []
    assert response["action"]["args"]["next_steps"] == []
