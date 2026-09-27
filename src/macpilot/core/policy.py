"""Deterministic action-risk policy for workflow routing."""

from __future__ import annotations

from typing import Any


HIGH_RISK_TOOLS = frozenset({
    "submit_form",
    "delete_file",
    "run_command",
    "send_message",
    "upload_file",
})

HIGH_RISK_PHRASES = (
    "提交申请",
    "提交简历",
    "提交表单",
    "submit application",
    "submit form",
    "submit resume",
    "apply now",
    "申请职位",
)


def _plan_tools(plan: dict[str, Any]) -> set[str]:
    tools: set[str] = set()
    for step in plan.get("steps", []) if isinstance(plan, dict) else []:
        if isinstance(step, dict) and isinstance(step.get("tool"), str):
            tools.add(step["tool"])
    return tools


def requires_approval(goal: str, plan: dict[str, Any] | None = None) -> bool:
    """Return whether a goal contains an action that must be approved."""
    normalized_goal = goal.casefold()
    if any(phrase.casefold() in normalized_goal for phrase in HIGH_RISK_PHRASES):
        return True
    if _plan_tools(plan or {}) & HIGH_RISK_TOOLS:
        return True
    return bool((plan or {}).get("requires_approval"))


def risk_action(goal: str, plan: dict[str, Any] | None = None) -> str:
    """Describe the deterministic action category shown in an approval UI."""
    tools = _plan_tools(plan or {})
    if "submit_form" in tools or any(
        phrase.casefold() in goal.casefold() for phrase in HIGH_RISK_PHRASES
    ):
        return "submit_form"
    if tools & HIGH_RISK_TOOLS:
        return sorted(tools & HIGH_RISK_TOOLS)[0]
    return "external_action"
