"""Metrics for task traces and offline evaluation runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass
class EvaluationMetrics:
    task_count: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    success_rate: float = 0.0
    average_latency_ms: float = 0.0
    average_steps: float = 0.0
    average_tool_calls: float = 0.0
    recovery_attempts: int = 0
    recovered_tasks: int = 0
    recovery_rate: float = 0.0
    approval_requests: int = 0
    approved_requests: int = 0
    high_risk_intercepted: int = 0
    unauthorized_actions: int = 0
    prompt_injection_detected: int = 0
    prompt_injection_samples: int = 0
    citation_correct: int = 0
    citation_claims: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cache_hits: int = 0
    model_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["success_rate"] = round(self.success_rate, 4)
        value["recovery_rate"] = round(self.recovery_rate, 4)
        value["prompt_injection_detection_rate"] = (
            self.prompt_injection_detected / self.prompt_injection_samples
            if self.prompt_injection_samples else 0.0
        )
        value["citation_correctness"] = (
            self.citation_correct / self.citation_claims
            if self.citation_claims else 0.0
        )
        value["cache_hit_rate"] = self.cache_hits / self.model_calls if self.model_calls else 0.0
        value["high_risk_interception_rate"] = (
            self.high_risk_intercepted / self.approval_requests
            if self.approval_requests else 0.0
        )
        return value


def _duration_ms(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    except ValueError:
        return 0.0


def summarize_task_traces(traces: Iterable[dict[str, Any]]) -> EvaluationMetrics:
    """Aggregate normalized task dictionaries without requiring a database."""
    metrics = EvaluationMetrics()
    durations: list[float] = []
    step_counts: list[int] = []
    tool_counts: list[int] = []
    for trace in traces:
        metrics.task_count += 1
        status = trace.get("status")
        metrics.completed_tasks += status == "completed" or trace.get("passed") is True
        metrics.failed_tasks += status in {"failed", "cancelled"} or trace.get("passed") is False
        duration = trace.get("latency_ms", 0.0)
        if not duration:
            duration = _duration_ms(trace.get("created_at"), trace.get("updated_at"))
        durations.append(float(duration))
        steps = trace.get("steps", [])
        step_counts.append(len(steps))
        events = trace.get("events", [])
        tool_counts.append(sum(event.get("event_type") == "tool_call" for event in events))
        metrics.recovery_attempts += sum(
            event.get("event_type") in {"retry", "recovery_attempted"} for event in events
        )
        metrics.recovered_tasks += bool(
            any(event.get("event_type") == "recovery_succeeded" for event in events)
            or (trace.get("recovered") is True)
        )
        metrics.approval_requests += sum(event.get("event_type") == "approval_requested" for event in events)
        metrics.approved_requests += sum(
            event.get("event_type") == "approval_resolved"
            and event.get("payload", {}).get("status") == "approved"
            for event in events
        )
        metrics.high_risk_intercepted += sum(
            event.get("event_type") in {"approval_requested", "waiting_approval"}
            for event in events
        )
        for event in events:
            output = event.get("payload", {}).get("output", {})
            if event.get("event_type") == "tool_call" and output.get("policy_denied"):
                metrics.unauthorized_actions += 1
            if event.get("event_type") == "model_usage":
                payload = event.get("payload", {})
                metrics.model_calls += 1
                metrics.input_tokens += int(payload.get("input_tokens", 0))
                metrics.output_tokens += int(payload.get("output_tokens", 0))
                metrics.cache_hits += int(bool(payload.get("cache_hit")))
                metrics.estimated_cost_usd += float(payload.get("estimated_cost_usd", 0.0))
            if event.get("event_type") == "prompt_injection_detected":
                metrics.prompt_injection_detected += 1
                metrics.prompt_injection_samples += 1
    metrics.total_tokens = metrics.input_tokens + metrics.output_tokens
    if metrics.task_count:
        metrics.success_rate = metrics.completed_tasks / metrics.task_count
        metrics.recovery_rate = metrics.recovered_tasks / metrics.task_count
    if durations:
        metrics.average_latency_ms = sum(durations) / len(durations)
    if step_counts:
        metrics.average_steps = sum(step_counts) / len(step_counts)
    if tool_counts:
        metrics.average_tool_calls = sum(tool_counts) / len(tool_counts)
    return metrics


def summarize_events(events: list[dict[str, Any]], task: dict[str, Any] | None = None,
                     steps: list[dict[str, Any]] | None = None) -> EvaluationMetrics:
    """Convenience wrapper for one task returned by ``SQLiteStore``."""
    task = task or {}
    return summarize_task_traces([{
        **task,
        "events": events,
        "steps": steps or [],
    }])
