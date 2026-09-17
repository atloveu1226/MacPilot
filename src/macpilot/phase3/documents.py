"""Safe extraction of text and tables from common office documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool

from macpilot.core.config import Settings
from macpilot.phase1.filesystem import (
    TEXT_EXTENSIONS,
    WorkspacePolicyError,
    resolve_workspace_path,
)


DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xlsm", *TEXT_EXTENSIONS}


def _check_document(path: Path, settings: Settings, relative_path: str) -> dict[str, Any] | None:
    if not path.is_file():
        return {"ok": False, "error": f"File not found: {relative_path}"}
    if path.suffix.lower() not in DOCUMENT_EXTENSIONS:
        return {"ok": False, "error": f"Unsupported document type: {path.suffix}"}
    if path.stat().st_size > settings.max_file_bytes:
        return {"ok": False, "error": "File exceeds the configured size limit."}
    return None


def extract_document(path: Path, max_file_bytes: int) -> str:
    """Extract bounded UTF-8-like text from a PDF, Word, Excel, or text file."""
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        import fitz

        with fitz.open(path) as document:
            return "\n\n".join(page.get_text() for page in document)
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            parts.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
        return "\n".join(parts)
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            parts: list[str] = []
            for worksheet in workbook.worksheets:
                parts.append(f"[Sheet: {worksheet.title}]")
                for row in worksheet.iter_rows(values_only=True):
                    values = ["" if value is None else str(value) for value in row]
                    if any(values):
                        parts.append(" | ".join(values))
            return "\n".join(parts)
        finally:
            workbook.close()
    raise ValueError(f"Unsupported document type: {suffix}")


def make_document_tools(
    settings: Settings,
    audit_store: Any | None = None,
    task_id: str | None = None,
) -> list[StructuredTool]:
    def audit(tool_name: str, input_data: Any, output_data: Any) -> None:
        if audit_store is not None:
            audit_store.append_event(
                "tool_call",
                {"tool_name": tool_name, "input": input_data, "output": output_data},
                task_id=task_id,
            )

    def result(tool_name: str, input_data: Any, output_data: dict[str, Any]) -> dict[str, Any]:
        audit(tool_name, input_data, output_data)
        return output_data

    @tool
    def read_document(relative_path: str) -> dict[str, Any]:
        """Read a supported document inside the allowed workspace with source metadata."""
        try:
            path = resolve_workspace_path(settings, relative_path)
        except WorkspacePolicyError as error:
            return result(
                "read_document",
                {"relative_path": relative_path},
                {"ok": False, "error": str(error), "policy_denied": True},
            )
        problem = _check_document(path, settings, relative_path)
        if problem:
            return result("read_document", {"relative_path": relative_path}, problem)
        try:
            text = extract_document(path, settings.max_file_bytes)
        except Exception as error:
            return result(
                "read_document",
                {"relative_path": relative_path},
                {"ok": False, "error": f"Document extraction failed: {error}"},
            )
        bounded_text = text[: settings.max_file_bytes]
        return result(
            "read_document",
            {"relative_path": relative_path},
            {
                "ok": True,
                "source": str(path.relative_to(settings.workspace.expanduser().resolve())),
                "format": path.suffix.lower().lstrip("."),
                "content": bounded_text,
                "truncated": len(text) > len(bounded_text),
            },
        )

    return [read_document]
