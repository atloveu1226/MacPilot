from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from macpilot.core.checkpoint import make_sqlite_checkpointer


class CounterState(TypedDict):
    count: int


def _counter_workflow(checkpointer):
    def increment(state: CounterState) -> dict[str, int]:
        return {"count": state["count"] + 1}

    builder = StateGraph(CounterState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


def test_sqlite_checkpoint_survives_reopen(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite3"
    checkpointer, connection = make_sqlite_checkpointer(database)
    config = {"configurable": {"thread_id": "thread-1"}}

    first = _counter_workflow(checkpointer).invoke({"count": 0}, config)
    assert first["count"] == 1
    connection.close()

    reopened_checkpointer, reopened_connection = make_sqlite_checkpointer(database)
    try:
        second = _counter_workflow(reopened_checkpointer).invoke({}, config)
        assert second["count"] == 2
    finally:
        reopened_connection.close()
