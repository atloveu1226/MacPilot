from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
from typing import Any, Literal
import re
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    session_id: str | None = None


class CreateSessionRequest(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=120)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class ResolveApprovalRequest(BaseModel):
    status: Literal["approved", "rejected"]


SUPPORTED_UPLOAD_EXTENSIONS = {
    ".csv",
    ".docx",
    ".json",
    ".md",
    ".pdf",
    ".txt",
    ".xlsm",
    ".xlsx",
    ".yaml",
    ".yml",
}
MAX_FILES_PER_TASK = 20


def _session_file_directory(settings: Settings, session_id: str) -> Path:
    return settings.workspace.expanduser().resolve() / "uploads" / session_id


def _safe_upload_filename(filename: str | None) -> str:
    original = Path(filename or "").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    return cleaned


def _list_task_files(settings: Settings, session_id: str) -> list[dict[str, Any]]:
    directory = _session_file_directory(settings, session_id)
    if not directory.is_dir():
        return []
    workspace = settings.workspace.expanduser().resolve()
    files: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        files.append({
            "name": path.name,
            "path": str(path.relative_to(workspace)),
            "size": path.stat().st_size,
            "format": path.suffix.lower().lstrip("."),
        })
    return files


def _task_dict(task: TaskRecord) -> dict[str, Any]:
    return {
        "id": task.id,
        "session_id": task.session_id,
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
        allow_methods=["GET", "POST", "DELETE"],
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

    def session_dict(session: Any) -> dict[str, Any]:
        return {
            "id": session.id,
            "title": session.title,
            "status": session.status,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "archived_at": session.archived_at,
        }

    @app.get("/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return [session_dict(item) for item in store.list_sessions()]

    @app.post("/sessions", status_code=status.HTTP_201_CREATED)
    def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
        session_id = store.create_session(payload.title)
        return session_dict(store.get_session(session_id))

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session_dict(session)

    @app.get("/sessions/{session_id}/messages")
    def list_session_messages(session_id: str) -> list[dict[str, Any]]:
        if store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return [
            {
                "id": item.id,
                "session_id": item.session_id,
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at,
                "run_id": item.run_id,
            }
            for item in store.list_messages(session_id)
        ]

    @app.get("/sessions/{session_id}/task")
    def get_session_task(session_id: str) -> dict[str, Any] | None:
        if store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        task = store.get_session_task(session_id)
        return _task_dict(task) if task else None

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, Any]:
        if store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            deleted = store.delete_session(session_id)
            directory = _session_file_directory(settings, session_id)
            workspace_uploads = settings.workspace.expanduser().resolve() / "uploads"
            if directory.parent == workspace_uploads and directory.is_dir():
                shutil.rmtree(directory)
        except (OSError, KeyError) as error:
            raise HTTPException(status_code=500, detail=f"删除会话失败：{error}") from error
        return {"ok": True, "session_id": session_id, "deleted": deleted}

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
        if payload.session_id and store.get_session(payload.session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        task_id = store.create_task(
            payload.user_goal,
            plan=payload.plan,
            session_id=payload.session_id,
        )
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

    @app.get("/tasks/{task_id}/files")
    def list_files(task_id: str) -> list[dict[str, Any]]:
        task = get_task_or_404(task_id)
        return _list_task_files(settings, task.session_id)

    @app.post("/tasks/{task_id}/files", status_code=status.HTTP_201_CREATED)
    def upload_file(task_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        task = get_task_or_404(task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="已结束的任务不能上传文件")

        filename = _safe_upload_filename(file.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))
            raise HTTPException(status_code=415, detail=f"不支持的文件类型。支持：{allowed}")

        existing = _list_task_files(settings, task.session_id)
        if len(existing) >= MAX_FILES_PER_TASK:
            raise HTTPException(status_code=413, detail=f"每个任务最多上传 {MAX_FILES_PER_TASK} 个文件")

        directory = _session_file_directory(settings, task.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        if destination.exists():
            destination = directory / f"{destination.stem}-{uuid.uuid4().hex[:8]}{destination.suffix}"

        byte_count = 0
        try:
            with destination.open("wb") as output:
                while chunk := file.file.read(64 * 1024):
                    byte_count += len(chunk)
                    if byte_count > settings.max_file_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"文件不能超过 {settings.max_file_bytes} 字节",
                        )
                    output.write(chunk)
        except HTTPException:
            destination.unlink(missing_ok=True)
            raise
        except OSError as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"文件保存失败：{error}") from error
        finally:
            file.file.close()

        workspace = settings.workspace.expanduser().resolve()
        metadata = {
            "name": destination.name,
            "original_name": filename,
            "path": str(destination.relative_to(workspace)),
            "size": byte_count,
            "format": suffix.lstrip("."),
        }
        store.append_event("file_uploaded", metadata, task_id=task_id)
        return metadata

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
        task = get_task_or_404(task_id)
        workflow = build_agent_workflow(
            settings,
            audit_store=store,
            task_id=task_id,
            session_id=task.session_id,
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
        store.append_message(task.session_id, "assistant", response, run_id=step_id)
        store.update_task_status(
            task_id,
            "cancelled" if result.get("approval_status") == "rejected" else "completed",
        )
        return {
            "task": _task_dict(get_task_or_404(task_id)),
            "step_id": step_id,
            "response": response,
        }

    def _thinking_message(event: dict[str, Any]) -> str | None:
        """Expose safe progress summaries, never hidden chain-of-thought."""
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if event_type == "agent_started":
            return {
                "Planner": "正在理解任务并制定计划",
                "Researcher": "正在检索和分析相关资料",
                "Critic": "正在核对证据和结果质量",
                "Finalizer": "正在整理最终结论",
                "Approval Gate": "正在确认是否需要你的批准",
                "Executor": "正在执行已批准的外部操作",
            }.get(str(payload.get("agent_name")), "正在处理任务")
        if event_type == "tool_call":
            tool_name = str(payload.get("tool_name", "资料工具"))
            if tool_name == "search_knowledge":
                return "正在搜索知识库中的相关内容"
            if tool_name in {"read_file", "read_document"}:
                return "正在读取相关资料"
            if tool_name == "fetch_page":
                return "正在查看允许访问的网页资料"
            if tool_name == "open_page":
                return "正在打开允许访问的网页"
            if tool_name == "inspect_form":
                return "正在识别网页表单字段"
            if tool_name == "fill_form":
                return "正在填写网页表单草稿"
            if tool_name == "submit_form":
                return "正在执行已批准的表单提交"
            return "正在调用必要工具"
        if event_type == "waiting_approval":
            return "任务需要你的批准才能继续"
        if event_type == "error":
            return "处理时遇到问题"
        return None

    def _sse(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @app.post("/tasks/{task_id}/messages/stream")
    async def stream_message(task_id: str, payload: MessageRequest):
        """Run a task and stream safe progress summaries plus the conclusion."""
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
        task = get_task_or_404(task_id)
        store.append_message(task.session_id, "user", payload.content, run_id=step_id)

        async def events() -> AsyncIterator[str]:
            yield _sse("thinking", {"message": "正在启动 MacPilot"})
            runner = asyncio.create_task(
                asyncio.to_thread(
                    run_workflow,
                    task_id,
                    step_id,
                    {"messages": [HumanMessage(content=payload.content)]},
                )
            )
            seen: set[str] = set()
            while not runner.done():
                for event in store.list_events(task_id):
                    event_id = str(event["id"])
                    if event_id in seen:
                        continue
                    seen.add(event_id)
                    message = _thinking_message(event)
                    if message:
                        yield _sse("thinking", {"message": message})
                await asyncio.sleep(0.2)
            try:
                result = await runner
            except HTTPException as error:
                yield _sse("error", {"message": error.detail})
                return
            except Exception as error:
                yield _sse("error", {"message": str(error)})
                return

            if result.get("interrupts"):
                yield _sse(
                    "approval",
                    {
                        "message": "任务需要审批后才能继续。",
                        "task": result["task"],
                    },
                )
                return
            response = str(result.get("response", ""))
            for start in range(0, len(response), 96):
                yield _sse("conclusion", {"delta": response[start : start + 96]})
                await asyncio.sleep(0.01)
            yield _sse("done", {"task": result["task"]})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
        task = get_task_or_404(task_id)
        store.append_message(task.session_id, "user", payload.content, run_id=step_id)

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
