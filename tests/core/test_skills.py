from pathlib import Path

import pytest

from macpilot.core.skills import SkillNotFoundError, load_skill


def test_load_skill_uses_standard_skill_entrypoint() -> None:
    content = load_skill("readcv")
    assert "name: readcv" in content
    assert "Project Experience" in content


def test_load_skill_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        load_skill("../readcv")


def test_load_skill_reports_missing_skill(tmp_path: Path) -> None:
    with pytest.raises(SkillNotFoundError):
        load_skill("missing", root=tmp_path)
