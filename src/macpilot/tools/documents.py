"""Compatibility import; implementation lives in :mod:`macpilot.phase3`."""

from macpilot.phase3.documents import (
    DOCUMENT_EXTENSIONS,
    extract_document,
    make_document_tools,
)

__all__ = ["DOCUMENT_EXTENSIONS", "extract_document", "make_document_tools"]
