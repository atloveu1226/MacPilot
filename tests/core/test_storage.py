from pathlib import Path

from macpilot.core.storage import SQLiteStore


def test_task_steps_and_events_survive_reopen(tmp_path: Path) -> None:
    database = tmp_path / "macpilot.sqlite3"
    store = SQLiteStore(database)
    task_id = store.create_task("整理项目资料", plan={"steps": ["scan", "summarize"]})
    step_id = store.create_step(task_id, "File Analyst", input_data={"path": "."})
    store.append_event("tool_call", {"tool_name": "list_files"}, task_id, step_id)
    store.finish_step(step_id, "completed", {"files": 2})
    store.update_task_status(task_id, "completed")

    reopened = SQLiteStore(database)
    task = reopened.get_task(task_id)

    assert task is not None
    assert task.status == "completed"
    assert task.plan == {"steps": ["scan", "summarize"]}
    assert reopened.list_steps(task_id)[0]["status"] == "completed"
    assert reopened.list_events(task_id)[0]["event_type"] == "tool_call"


def test_approval_lifecycle_is_audited(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "macpilot.sqlite3")
    task_id = store.create_task("提交表单")
    approval_id = store.create_approval(
        task_id,
        action_type="submit_form",
        risk_reason="会向第三方网站提交信息",
        preview="提交 4 个已填写字段",
    )

    store.resolve_approval(approval_id, "approved")
    event_types = [event["event_type"] for event in store.list_events(task_id)]

    assert event_types == ["approval_requested", "approval_resolved"]
    assert store.list_approvals(task_id)[0]["status"] == "approved"


def test_invalid_runtime_status_is_rejected(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "macpilot.sqlite3")
    task_id = store.create_task("测试状态")

    try:
        store.update_task_status(task_id, "unknown")  # type: ignore[arg-type]
    except ValueError as error:
        assert "Unknown task status" in str(error)
    else:
        raise AssertionError("invalid task status should be rejected")
