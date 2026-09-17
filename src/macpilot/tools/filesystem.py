"""Compatibility import; implementation lives in :mod:`macpilot.phase1`."""

from macpilot.phase1.filesystem import (
    TEXT_EXTENSIONS,
    WorkspacePolicyError,
    make_filesystem_tools,
    resolve_workspace_path,
)

__all__ = [
    "TEXT_EXTENSIONS",
    "WorkspacePolicyError",
    "make_filesystem_tools",
    "resolve_workspace_path",
]
