"""Persistent, local response cache used for repeatable model work.

Only model responses are cached.  Tool results and approvals remain live so a
cache hit can never bypass a filesystem or high-risk policy check.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


def make_cache_key(model: str, messages: Any, version: str = "v1") -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "version": version},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """A small SQLite-backed cache that shares the agent's local database."""

    def __init__(self, database_path: Path | str, ttl_seconds: float = 86_400) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        with closing(self._connection()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0
                )"""
            )
            connection.commit()

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def get(self, key: str) -> str | None:
        now = datetime.now(timezone.utc).timestamp()
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT response_text, created_at FROM llm_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if self.ttl_seconds >= 0 and now - row[1] > self.ttl_seconds:
                connection.execute("DELETE FROM llm_cache WHERE cache_key = ?", (key,))
                connection.commit()
                return None
            connection.execute(
                "UPDATE llm_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (key,),
            )
            connection.commit()
            return row[0]

    def set(self, key: str, model: str, response_text: str) -> None:
        with closing(self._connection()) as connection:
            connection.execute(
                """INSERT INTO llm_cache(cache_key, model, response_text, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     model=excluded.model, response_text=excluded.response_text,
                     created_at=excluded.created_at, hit_count=0""",
                (key, model, response_text, datetime.now(timezone.utc).timestamp()),
            )
            connection.commit()

    def stats(self) -> dict[str, int]:
        with closing(self._connection()) as connection:
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM llm_cache"
            ).fetchone()
        return {"entries": int(row[0]), "hits": int(row[1])}

    def clear(self) -> None:
        with closing(self._connection()) as connection:
            connection.execute("DELETE FROM llm_cache")
            connection.commit()
