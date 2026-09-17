from pathlib import Path

import pytest

from macpilot.core.config import Settings
from macpilot.phase1.filesystem import WorkspacePolicyError, resolve_workspace_path
from macpilot.phase1.filesystem import make_filesystem_tools


def test_path_stays_inside_workspace(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path)
    assert resolve_workspace_path(settings, "profile.md") == tmp_path / "profile.md"


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path)
    with pytest.raises(WorkspacePolicyError):
        resolve_workspace_path(settings, "../secret.txt")


def test_write_is_blocked_by_default(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path)
    write_file = make_filesystem_tools(settings)[2]

    result = write_file.invoke({"relative_path": "summary.md", "content": "hello"})

    assert result["ok"] is False
    assert not (tmp_path / "summary.md").exists()


def test_write_is_allowed_only_inside_workspace(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path, read_only=False)
    write_file = make_filesystem_tools(settings)[2]

    result = write_file.invoke({"relative_path": "nested/summary.md", "content": "hello"})

    assert result["ok"] is True
    assert (tmp_path / "nested/summary.md").read_text() == "hello"

    escaped = write_file.invoke({"relative_path": "../summary.md", "content": "nope"})
    assert escaped["ok"] is False
