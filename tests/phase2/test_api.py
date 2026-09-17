from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Command

from macpilot.api import create_app
from macpilot.core.config import Settings


class FakeAgent:
    def invoke(self, *_args, **_kwargs):
        return {"messages": [AIMessage(content="测试回复") ]}


def test_task_api_records_messages_and_events(tmp_path: Path, monkeypatch) -> None:
    from macpilot import api

    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    monkeypatch.setattr(api, "build_agent_workflow", lambda *args, **kwargs: FakeAgent())
    client = TestClient(create_app(settings))

    created = client.post("/tasks", json={"user_goal": "测试任务"})
    assert created.status_code == 201
    task_id = created.json()["id"]

    response = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "你好"},
    )
    assert response.status_code == 200
    assert response.json()["response"] == "测试回复"

    events = client.get(f"/tasks/{task_id}/events").json()
    assert [event["event_type"] for event in events] == [
        "task_created",
        "user_message",
        "assistant_message",
    ]


def test_approval_api_resolves_only_approvals_for_task(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    client = TestClient(create_app(settings))

    created = client.post("/tasks", json={"user_goal": "提交表单"})
    task_id = created.json()["id"]
    store = client.app.state.store
    approval_id = store.create_approval(
        task_id,
        action_type="submit_form",
        risk_reason="会向第三方网站提交信息",
        preview="提交 4 个已填写字段",
    )

    approvals = client.get(f"/tasks/{task_id}/approvals")
    assert approvals.status_code == 200
    assert approvals.json()[0]["status"] == "pending"

    resolved = client.post(
        f"/tasks/{task_id}/approvals/{approval_id}",
        json={"status": "approved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"


def test_task_api_can_pause_and_resume(tmp_path: Path, monkeypatch) -> None:
    from macpilot import api

    class InterruptingAgent:
        def invoke(self, input_data, **_kwargs):
            if isinstance(input_data, Command):
                return {"messages": [AIMessage(content="恢复完成") ]}
            return {
                "__interrupt__": [
                    SimpleNamespace(
                        value={"approval_id": "approval-1", "message": "请确认"}
                    )
                ]
            }

    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    monkeypatch.setattr(api, "build_agent_workflow", lambda *args, **kwargs: InterruptingAgent())
    client = TestClient(create_app(settings))
    task_id = client.post("/tasks", json={"user_goal": "需要审批的任务"}).json()["id"]

    paused = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "执行高风险动作"},
    )
    assert paused.status_code == 200
    assert paused.json()["response"] == "任务暂停，等待人工审批。"
    assert paused.json()["task"]["status"] == "waiting_approval"

    resumed = client.post(
        f"/tasks/{task_id}/resume",
        json={"status": "approved"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["response"] == "恢复完成"


def test_task_api_can_cancel_pending_task(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    client = TestClient(create_app(settings))
    task_id = client.post("/tasks", json={"user_goal": "待终止任务"}).json()["id"]

    response = client.post(f"/tasks/{task_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_metrics_api_aggregates_persisted_task_trace(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    client = TestClient(create_app(settings))
    task_id = client.post("/tasks", json={"user_goal": "指标任务"}).json()["id"]
    client.post(f"/tasks/{task_id}/cancel")

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["task_count"] == 1
    assert metrics.json()["failed_tasks"] == 1

    task_metrics = client.get(f"/tasks/{task_id}/metrics")
    assert task_metrics.status_code == 200
    assert task_metrics.json()["task_count"] == 1
