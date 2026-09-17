from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def make_sqlite_checkpointer(
    database_path: Path | str,
) -> tuple[SqliteSaver, sqlite3.Connection]:
    """Create a durable LangGraph checkpoint saver and keep its connection alive."""
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer, connection
