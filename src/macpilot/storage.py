"""Compatibility import; new code should use :mod:`macpilot.core.storage`."""

from macpilot.core.storage import SQLiteStore, TaskRecord

__all__ = ["SQLiteStore", "TaskRecord"]
