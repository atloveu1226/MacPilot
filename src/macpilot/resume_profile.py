"""Compatibility import; new code should use :mod:`macpilot.phase3.resume_profile`."""

from macpilot.phase3.resume_profile import (
    Basics,
    EducationEntry,
    Evidence,
    ExperienceEntry,
    ProjectEntry,
    RESUME_EXTRACTION_PROMPT,
    ResumeProfile,
    parse_resume_profile,
)

__all__ = [
    "Basics",
    "EducationEntry",
    "Evidence",
    "ExperienceEntry",
    "ProjectEntry",
    "RESUME_EXTRACTION_PROMPT",
    "ResumeProfile",
    "parse_resume_profile",
]
