from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from macpilot.api import create_app
from macpilot.core.config import Settings


class FakeAgent:
    def invoke(self, *_args, **_kwargs):
        return {"messages": [AIMessage(content="流式测试结论") ]}


def test_stream_message_returns_thinking_and_conclusion(tmp_path: Path, monkeypatch) -> None:
    from macpilot import api

    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    monkeypatch.setattr(api, "build_agent_workflow", lambda *args, **kwargs: FakeAgent())
    client = TestClient(create_app(settings))
    task_id = client.post("/tasks", json={"user_goal": "流式任务"}).json()["id"]

    response = client.post(
        f"/tasks/{task_id}/messages/stream",
        json={"content": "请输出结论"},
    )

    assert response.status_code == 200
    assert "event: thinking" in response.text
    assert "event: conclusion" in response.text
    assert "流式测试结论" in response.text
    assert "event: done" in response.text
