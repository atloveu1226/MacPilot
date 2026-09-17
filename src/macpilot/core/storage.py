"""Durable task, step, approval, and audit-event storage.

The store deliberately uses a small SQLite schema so the prototype remains
local-first while making every task inspectable after the process exits.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from macpilot.core.models import ApprovalStatus, StepStatus, TaskStatus

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


@dataclass(frozen=True)
class TaskRecord:
    id: str
    user_goal: str
    status: str
    plan: Any
    created_at: str
    updated_at: str


class SQLiteStore:
    """Persist workflow state and an append-only audit trail."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connection()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    user_goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    agent_name TEXT NOT NULL,
                    tool_name TEXT,
                    input_json TEXT,
                    output_json TEXT,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    step_id TEXT REFERENCES steps(id),
                    action_type TEXT NOT NULL,
                    risk_reason TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT REFERENCES tasks(id),
                    step_id TEXT REFERENCES steps(id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_steps_task ON steps(task_id, started_at);
                """
            )
            connection.commit()

    def create_task(self, user_goal: str, plan: Any = None, task_id: str | None = None) -> str:
        task_id = task_id or str(uuid.uuid4())
        timestamp = _now()
        with closing(self._connection()) as connection:
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, user_goal, "pending", _json(plan) if plan is not None else None,
                 timestamp, timestamp),
            )
            connection.commit()
        return task_id

    def get_task(self, task_id: str) -> TaskRecord | None:
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            id=row["id"],
            user_goal=row["user_goal"],
            status=row["status"],
            plan=json.loads(row["plan_json"]) if row["plan_json"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_tasks(self, status: str | None = None) -> list[TaskRecord]:
        """Return persisted tasks for reporting and local operator tooling."""
        query = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at, id"
        with closing(self._connection()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            TaskRecord(
                id=row["id"],
                user_goal=row["user_goal"],
                status=row["status"],
                plan=json.loads(row["plan_json"]) if row["plan_json"] else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        if status not in {
            "pending",
            "running",
            "waiting_approval",
            "failed",
            "completed",
            "cancelled",
        }:
            raise ValueError(f"Unknown task status: {status}")
        with closing(self._connection()) as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), task_id),
            )
            connection.commit()

    def create_step(
        self,
        task_id: str,
        agent_name: str,
        tool_name: str | None = None,
        input_data: Any = None,
        status: StepStatus = "running",
        step_id: str | None = None,
    ) -> str:
        step_id = step_id or str(uuid.uuid4())
        with closing(self._connection()) as connection:
            connection.execute(
                """INSERT INTO steps
                   (id, task_id, agent_name, tool_name, input_json, status, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (step_id, task_id, agent_name, tool_name,
                 _json(input_data) if input_data is not None else None,
                 status, _now()),
            )
            connection.commit()
        return step_id

    def finish_step(self, step_id: str, status: StepStatus, output_data: Any = None,
                    retry_count: int | None = None) -> None:
        if status not in {"running", "waiting_approval", "completed", "failed", "cancelled"}:
            raise ValueError(f"Unknown step status: {status}")
        assignments = ["status = ?", "output_json = ?", "finished_at = ?"]
        values: list[Any] = [status, _json(output_data) if output_data is not None else None, _now()]
        if retry_count is not None:
            assignments.append("retry_count = ?")
            values.append(retry_count)
        values.append(step_id)
        with closing(self._connection()) as connection:
            connection.execute(
                f"UPDATE steps SET {', '.join(assignments)} WHERE id = ?", values
            )
            connection.commit()

    def list_steps(self, task_id: str) -> list[dict[str, Any]]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT * FROM steps WHERE task_id = ? ORDER BY started_at, id",
                (task_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "agent_name": row["agent_name"],
                "tool_name": row["tool_name"],
                "input": json.loads(row["input_json"]) if row["input_json"] else None,
                "output": json.loads(row["output_json"]) if row["output_json"] else None,
                "status": row["status"],
                "retry_count": row["retry_count"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]

    def create_approval(
        self,
        task_id: str,
        action_type: str,
        risk_reason: str,
        preview: str,
        step_id: str | None = None,
        approval_id: str | None = None,
    ) -> str:
        approval_id = approval_id or str(uuid.uuid4())
        with closing(self._connection()) as connection:
            connection.execute(
                """INSERT INTO approvals
                   (id, task_id, step_id, action_type, risk_reason, preview,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (approval_id, task_id, step_id, action_type, risk_reason, preview, _now()),
            )
            connection.commit()
        self.append_event(
            "approval_requested",
            {"action_type": action_type, "risk_reason": risk_reason, "preview": preview},
            task_id=task_id,
            step_id=step_id,
        )
        return approval_id

    def resolve_approval(self, approval_id: str, status: ApprovalStatus) -> None:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval status must be approved or rejected")
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT task_id, step_id FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Approval not found: {approval_id}")
            connection.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                (status, _now(), approval_id),
            )
            connection.commit()
        self.append_event(
            "approval_resolved",
            {"approval_id": approval_id, "status": status},
            task_id=row["task_id"],
            step_id=row["step_id"],
        )

    def list_approvals(self, task_id: str) -> list[dict[str, Any]]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "step_id": row["step_id"],
                "action_type": row["action_type"],
                "risk_reason": row["risk_reason"],
                "preview": row["preview"],
                "status": row["status"],
                "created_at": row["created_at"],
                "resolved_at": row["resolved_at"],
            }
            for row in rows
        ]

    def append_event(
        self,
        event_type: str,
        payload: Any,
        task_id: str | None = None,
        step_id: str | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        with closing(self._connection()) as connection:
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, task_id, step_id, event_type, _json(payload), _now()),
            )
            connection.commit()
        return event_id

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "step_id": row["step_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
