from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from macpilot.core.checkpoint import make_sqlite_checkpointer
from macpilot.core.config import Settings
from macpilot.core.storage import SQLiteStore, TaskRecord
from macpilot.phase2.workflow import build_agent_workflow
from macpilot.phase5.metrics import summarize_task_traces


class CreateTaskRequest(BaseModel):
    user_goal: str = Field(min_length=1, max_length=10_000)
    plan: dict[str, Any] | None = None


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class ResolveApprovalRequest(BaseModel):
    status: Literal["approved", "rejected"]


def _task_dict(task: TaskRecord) -> dict[str, Any]:
    return {
        "id": task.id,
        "user_goal": task.user_goal,
        "status": task.status,
        "plan": task.plan,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _interrupt_payloads(result: dict[str, Any]) -> list[Any]:
    return [
        getattr(item, "value", item)
        for item in result.get("__interrupt__", ())
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    load_dotenv(override=True)
    settings = settings or Settings.from_env()
    store = SQLiteStore(settings.database_path)
    checkpointer, checkpoint_connection = make_sqlite_checkpointer(
        settings.database_path
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            checkpoint_connection.close()

    app = FastAPI(
        title="MacPilot API",
        version="0.1.0",
        description="Task and event API for the local-first MacPilot agent.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.settings = settings
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.checkpoint_connection = checkpoint_connection

    def get_task_or_404(task_id: str) -> TaskRecord:
        task = store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "macpilot"}

    def task_trace(task: TaskRecord) -> dict[str, Any]:
        return {
            "id": task.id,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "events": store.list_events(task.id),
            "steps": store.list_steps(task.id),
        }

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        """Aggregate persisted task traces for the desktop and reports."""
        return summarize_task_traces(
            task_trace(task) for task in store.list_tasks()
        ).as_dict()

    @app.get("/tasks/{task_id}/metrics")
    def task_metrics(task_id: str) -> dict[str, Any]:
        task = get_task_or_404(task_id)
        return summarize_task_traces([task_trace(task)]).as_dict()

    @app.post("/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
        task_id = store.create_task(payload.user_goal, plan=payload.plan)
        store.append_event(
            "task_created",
            {"user_goal": payload.user_goal},
            task_id=task_id,
        )
        return _task_dict(get_task_or_404(task_id))

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        return _task_dict(get_task_or_404(task_id))

    @app.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        task = get_task_or_404(task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Task is already finished")
        store.update_task_status(task_id, "cancelled")
        store.append_event("task_cancelled", {}, task_id=task_id)
        return _task_dict(get_task_or_404(task_id))

    @app.get("/tasks/{task_id}/steps")
    def list_steps(task_id: str) -> list[dict[str, Any]]:
        get_task_or_404(task_id)
        return store.list_steps(task_id)

    @app.get("/tasks/{task_id}/events")
    def list_events(task_id: str) -> list[dict[str, Any]]:
        get_task_or_404(task_id)
        return store.list_events(task_id)

    @app.get("/tasks/{task_id}/approvals")
    def list_approvals(task_id: str) -> list[dict[str, Any]]:
        get_task_or_404(task_id)
        return store.list_approvals(task_id)

    @app.post("/tasks/{task_id}/approvals/{approval_id}")
    def resolve_approval(
        task_id: str,
        approval_id: str,
        payload: ResolveApprovalRequest,
    ) -> dict[str, Any]:
        get_task_or_404(task_id)
        approvals = {
            approval["id"]: approval for approval in store.list_approvals(task_id)
        }
        if approval_id not in approvals:
            raise HTTPException(status_code=404, detail="Approval not found")
        try:
            store.resolve_approval(approval_id, payload.status)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return next(
            approval
            for approval in store.list_approvals(task_id)
            if approval["id"] == approval_id
        )

    def run_workflow(
        task_id: str,
        step_id: str,
        workflow_input: Any,
    ) -> dict[str, Any]:
        workflow = build_agent_workflow(
            settings,
            audit_store=store,
            task_id=task_id,
            checkpointer=checkpointer,
        )
        try:
            result = workflow.invoke(
                workflow_input,
                config={"configurable": {"thread_id": task_id}},
            )
        except Exception as error:
            store.finish_step(step_id, "failed", {"error": str(error)})
            store.append_event(
                "error",
                {"message": str(error)},
                task_id=task_id,
                step_id=step_id,
            )
            store.update_task_status(task_id, "failed")
            raise HTTPException(
                status_code=502,
                detail="Agent execution failed; inspect the task events.",
            ) from error

        interruptions = _interrupt_payloads(result)
        if interruptions:
            store.finish_step(
                step_id,
                "waiting_approval",
                {"interrupts": interruptions},
            )
            store.append_event(
                "waiting_approval",
                {"interrupts": interruptions},
                task_id=task_id,
                step_id=step_id,
            )
            store.update_task_status(task_id, "waiting_approval")
            return {
                "task": _task_dict(get_task_or_404(task_id)),
                "step_id": step_id,
                "response": "任务暂停，等待人工审批。",
                "interrupts": interruptions,
            }

        if get_task_or_404(task_id).status == "cancelled":
            store.finish_step(step_id, "cancelled", {"response": "任务已终止。"})
            return {
                "task": _task_dict(get_task_or_404(task_id)),
                "step_id": step_id,
                "response": "任务已终止。",
            }

        response = result["messages"][-1].content
        if not isinstance(response, str):
            response = str(response)
        store.finish_step(step_id, "completed", {"response": response})
        store.append_event(
            "assistant_message",
            {"content": response},
            task_id=task_id,
            step_id=step_id,
        )
        store.update_task_status(
            task_id,
            "cancelled" if result.get("approval_status") == "rejected" else "completed",
        )
        return {
            "task": _task_dict(get_task_or_404(task_id)),
            "step_id": step_id,
            "response": response,
        }

    @app.post("/tasks/{task_id}/messages")
    def send_message(task_id: str, payload: MessageRequest) -> dict[str, Any]:
        get_task_or_404(task_id)
        store.update_task_status(task_id, "running")
        step_id = store.create_step(
            task_id,
            "MacPilot",
            input_data={"query": payload.content},
        )
        store.append_event(
            "user_message",
            {"content": payload.content},
            task_id=task_id,
            step_id=step_id,
        )

        return run_workflow(
            task_id,
            step_id,
            {"messages": [HumanMessage(content=payload.content)]},
        )

    @app.post("/tasks/{task_id}/resume")
    def resume_task(
        task_id: str,
        payload: ResolveApprovalRequest,
    ) -> dict[str, Any]:
        task = get_task_or_404(task_id)
        if task.status != "waiting_approval":
            raise HTTPException(
                status_code=409,
                detail="Task is not waiting for approval",
            )
        step_id = store.create_step(
            task_id,
            "MacPilot",
            input_data={"resume": payload.status},
        )
        store.append_event(
            "resume_requested",
            {"status": payload.status},
            task_id=task_id,
            step_id=step_id,
        )
        store.update_task_status(task_id, "running")
        return run_workflow(
            task_id,
            step_id,
            Command(resume={"status": payload.status}),
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("macpilot.api:app", host="127.0.0.1", port=8000, reload=False)
