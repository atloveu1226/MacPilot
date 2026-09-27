"""Runtime loader for project-local Agent Skills."""

from __future__ import annotations

import re
from pathlib import Path


_SAFE_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class SkillNotFoundError(FileNotFoundError):
    """Raised when a requested project skill has no standard SKILL.md entrypoint."""


def project_root() -> Path:
    """Return the repository root containing the source package."""
    return Path(__file__).resolve().parents[3]


def load_skill(name: str, root: Path | None = None) -> str:
    """Load a project skill from ``skills/<name>/SKILL.md``.

    Skill names are deliberately restricted to prevent path traversal. The
    returned text is intended to be inserted into a model's system prompt.
    """
    if not _SAFE_SKILL_NAME.fullmatch(name):
        raise ValueError(f"Invalid skill name: {name!r}")
    skill_path = (root or project_root()) / "skills" / name / "SKILL.md"
    if not skill_path.is_file():
        raise SkillNotFoundError(f"Skill entrypoint not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


__all__ = ["SkillNotFoundError", "load_skill", "project_root"]
