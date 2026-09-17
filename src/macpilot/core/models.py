"""Shared contracts used by the task runtime and future LangGraph nodes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage


TaskStatus = Literal[
    "pending",
    "running",
    "waiting_approval",
    "failed",
    "completed",
    "cancelled",
]
StepStatus = Literal[
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
ApprovalStatus = Literal["pending", "approved", "rejected"]


class AgentState(TypedDict, total=False):
    """Minimal state contract shared by the planned LangGraph workflow."""

    messages: list[BaseMessage]
    task_id: str
    plan: dict[str, Any]
    current_step_id: str
    research_notes: str
    critique: dict[str, Any]
    retry_count: int
    approval_id: str
    approval_status: ApprovalStatus


class TaskData(TypedDict):
    id: str
    user_goal: str
    status: TaskStatus
    plan: Any
    created_at: str
    updated_at: str


class StepData(TypedDict):
    id: str
    task_id: str
    agent_name: str
    tool_name: str | None
    input: Any
    output: Any
    status: StepStatus
    retry_count: int
    started_at: str | None
    finished_at: str | None


class ApprovalData(TypedDict):
    id: str
    task_id: str
    step_id: str | None
    action_type: str
    risk_reason: str
    preview: str
    status: ApprovalStatus
    created_at: str
    resolved_at: str | None


class EventData(TypedDict):
    id: str
    task_id: str | None
    step_id: str | None
    event_type: str
    payload: Any
    created_at: str


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for persisted records."""
    return datetime.now(timezone.utc).isoformat()
