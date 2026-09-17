from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool

from macpilot.core.config import Settings


TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
}


class WorkspacePolicyError(ValueError):
    """Raised when a filesystem request violates the workspace policy."""


def resolve_workspace_path(settings: Settings, relative_path: str) -> Path:
    """Resolve a user-provided path and guarantee it stays in the workspace."""
    root = settings.workspace.expanduser().resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise WorkspacePolicyError(
            f"Path is outside the allowed workspace: {relative_path}"
        )
    return candidate


def make_filesystem_tools(
    settings: Settings,
    audit_store: Any | None = None,
    task_id: str | None = None,
) -> list[StructuredTool]:
    settings.workspace.expanduser().mkdir(parents=True, exist_ok=True)

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
    def list_files(relative_path: str = ".") -> dict[str, Any]:
        """List files inside the allowed workspace directory."""
        try:
            directory = resolve_workspace_path(settings, relative_path)
        except WorkspacePolicyError as error:
            return result("list_files", {"relative_path": relative_path},
                          {"ok": False, "error": str(error)})
        if not directory.is_dir():
            return result("list_files", {"relative_path": relative_path},
                          {"ok": False, "error": f"Not a directory: {relative_path}"})

        files = [
            str(path.relative_to(settings.workspace.expanduser().resolve()))
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        ]
        return result("list_files", {"relative_path": relative_path},
                      {"ok": True, "files": files[:200], "truncated": len(files) > 200})

    @tool
    def read_file(relative_path: str) -> dict[str, Any]:
        """Read a small text file inside the allowed workspace directory."""
        try:
            path = resolve_workspace_path(settings, relative_path)
        except WorkspacePolicyError as error:
            return result("read_file", {"relative_path": relative_path},
                          {"ok": False, "error": str(error)})
        if not path.is_file():
            return result("read_file", {"relative_path": relative_path},
                          {"ok": False, "error": f"File not found: {relative_path}"})
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return result("read_file", {"relative_path": relative_path},
                          {"ok": False, "error": f"Unsupported text file type: {path.suffix}"})
        if path.stat().st_size > settings.max_file_bytes:
            return result("read_file", {"relative_path": relative_path},
                          {"ok": False, "error": "File exceeds the configured size limit."})

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return result("read_file", {"relative_path": relative_path},
                          {"ok": False, "error": "File is not valid UTF-8 text."})
        return result("read_file", {"relative_path": relative_path}, {
            "ok": True,
            "path": str(path.relative_to(settings.workspace.expanduser().resolve())),
            "content": content,
        })

    @tool
    def write_file(relative_path: str, content: str) -> dict[str, Any]:
        """Write a UTF-8 text file; disabled while the workspace is read-only."""
        input_data = {"relative_path": relative_path, "bytes": len(content.encode("utf-8"))}
        if settings.read_only:
            return result("write_file", input_data, {
                "ok": False,
                "error": "Workspace is read-only. Set MACPILOT_READ_ONLY=false to enable writes.",
            })
        try:
            path = resolve_workspace_path(settings, relative_path)
        except WorkspacePolicyError as error:
            return result("write_file", input_data, {"ok": False, "error": str(error)})
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return result("write_file", input_data, {
                "ok": False, "error": f"Unsupported text file type: {path.suffix}"
            })
        encoded = content.encode("utf-8")
        if len(encoded) > settings.max_file_bytes:
            return result("write_file", input_data, {
                "ok": False, "error": "Content exceeds the configured size limit."
            })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return result("write_file", input_data, {
            "ok": True,
            "path": str(path.relative_to(settings.workspace.expanduser().resolve())),
            "bytes_written": len(encoded),
        })

    return [list_files, read_file, write_file]
