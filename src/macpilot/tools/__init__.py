"""Compatibility exports for tools organized by implementation phase."""

from macpilot.phase1.filesystem import make_filesystem_tools
from macpilot.phase3.browser import make_browser_tools
from macpilot.phase3.documents import make_document_tools
from macpilot.phase3.knowledge import make_knowledge_tools

__all__ = [
    "make_browser_tools",
    "make_document_tools",
    "make_knowledge_tools",
    "make_filesystem_tools",
]
