"""Compatibility import; new code should use :mod:`macpilot.core.models`."""

from macpilot.core.models import (
    AgentState,
    ApprovalData,
    ApprovalStatus,
    EventData,
    StepData,
    StepStatus,
    TaskData,
    TaskStatus,
    utc_timestamp,
)

__all__ = [
    "AgentState",
    "ApprovalData",
    "ApprovalStatus",
    "EventData",
    "StepData",
    "StepStatus",
    "TaskData",
    "TaskStatus",
    "utc_timestamp",
]
