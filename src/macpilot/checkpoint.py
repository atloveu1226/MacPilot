"""Compatibility import; new code should use :mod:`macpilot.core.checkpoint`."""

from macpilot.core.checkpoint import make_sqlite_checkpointer

__all__ = ["make_sqlite_checkpointer"]
