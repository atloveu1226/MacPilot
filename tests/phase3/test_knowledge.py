from pathlib import Path

from macpilot.core.config import Settings
from macpilot.phase3.knowledge import KnowledgeIndex, make_knowledge_tools


def make_settings(tmp_path: Path) -> Settings:
    return Settings(workspace=tmp_path / "workspace", database_path=tmp_path / "db.sqlite3")


def test_knowledge_index_returns_sourced_chunks(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.workspace.mkdir(parents=True)
    (settings.workspace / "architecture.md").write_text(
        "# Workflow\n\nPlanner creates a plan. Researcher gathers evidence.\n\n"
        "# Security\n\nThe workspace is read-only by default.",
        encoding="utf-8",
    )

    result = KnowledgeIndex(settings).search("Researcher gathers evidence")

    assert result["ok"] is True
    assert result["results"][0]["source"] == "architecture.md"
    assert "Researcher" in result["results"][0]["content"]


def test_knowledge_tool_can_refresh_changed_file(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.workspace.mkdir(parents=True)
    document = settings.workspace / "notes.txt"
    document.write_text("old content", encoding="utf-8")
    tool = make_knowledge_tools(settings)[0]
    assert tool.invoke({"query": "old content"})["results"]

    document.write_text("new approval policy", encoding="utf-8")
    result = tool.invoke({"query": "new approval policy"})
    assert result["results"][0]["source"] == "notes.txt"


def test_knowledge_search_isolated_by_session(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    (settings.workspace / "uploads" / "session-a").mkdir(parents=True)
    (settings.workspace / "uploads" / "session-b").mkdir(parents=True)
    (settings.workspace / "uploads" / "session-a" / "notes.txt").write_text(
        "alpha private evidence", encoding="utf-8"
    )
    (settings.workspace / "uploads" / "session-b" / "notes.txt").write_text(
        "beta private evidence", encoding="utf-8"
    )

    result = KnowledgeIndex(settings).search("private evidence", session_id="session-a")

    sources = {item["source"] for item in result["results"]}
    assert "uploads/session-a/notes.txt" in sources
    assert "uploads/session-b/notes.txt" not in sources
