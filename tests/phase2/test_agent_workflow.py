from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from macpilot.core.config import Settings
from macpilot.core.storage import SQLiteStore
from macpilot.phase2.workflow import build_agent_workflow


class FakeToolCallingModel(FakeListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _build_test_context(tmp_path: Path, responses: list[str]):
    settings = Settings(
        workspace=tmp_path / "workspace",
        database_path=tmp_path / "macpilot.sqlite3",
    )
    store = SQLiteStore(settings.database_path)
    task_id = store.create_task("总结本地资料")
    model = FakeToolCallingModel(responses=responses)
    workflow = build_agent_workflow(
        settings,
        audit_store=store,
        task_id=task_id,
        model=model,
    )
    return workflow, store, task_id


def test_phase2_research_workflow_retries_after_critic(tmp_path: Path) -> None:
    workflow, store, task_id = _build_test_context(
        tmp_path,
        [
            '{"goal":"总结","steps":[],"constraints":[],"requires_approval":false}',
            "第一次研究笔记不完整",
            '{"approved":false,"issues":["缺少来源"],"missing_evidence":["profile.md"]}',
            "第二次研究笔记，来源：profile.md",
            '{"approved":true,"issues":[],"missing_evidence":[]}',
            "最终研究报告",
        ],
    )

    result = workflow.invoke(
        {"messages": [HumanMessage(content="总结本地资料")]},
        config={"configurable": {"thread_id": task_id}},
    )

    assert result["messages"][-1].content == "最终研究报告"
    assert [step["agent_name"] for step in store.list_steps(task_id)] == [
        "Planner",
        "Researcher",
        "Critic",
        "Researcher",
        "Critic",
        "Finalizer",
    ]


def test_phase2_approval_interrupt_can_resume(tmp_path: Path) -> None:
    workflow, store, task_id = _build_test_context(
        tmp_path,
        [
            '{"goal":"提交","steps":[],"constraints":[],"requires_approval":true}',
            "研究笔记",
            '{"approved":true,"issues":[],"missing_evidence":[]}',
            "审批后完成",
        ],
    )

    paused = workflow.invoke(
        {"messages": [HumanMessage(content="提交") ]},
        config={"configurable": {"thread_id": task_id}},
    )

    assert paused["__interrupt__"][0].value["approval_id"]
    assert store.get_task(task_id).status == "waiting_approval"
    approval_id = paused["__interrupt__"][0].value["approval_id"]

    resumed = workflow.invoke(
        Command(resume={"status": "approved"}),
        config={"configurable": {"thread_id": task_id}},
    )

    assert resumed["messages"][-1].content == "审批后完成"
    assert store.list_approvals(task_id)[0]["id"] == approval_id
    assert store.list_approvals(task_id)[0]["status"] == "approved"
