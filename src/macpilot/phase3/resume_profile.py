"""Evidence-aware resume data contracts for the Resume Autofill workflow."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Evidence(BaseModel):
    field: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class Basics(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None


class EducationEntry(BaseModel):
    school: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: str | None = None


class ExperienceEntry(BaseModel):
    company: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: str | None = None


class ProjectEntry(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    url: str | None = None


class ResumeProfile(BaseModel):
    basics: Basics = Field(default_factory=Basics)
    education: list[EducationEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_unsupported_evidence_sources(self) -> "ResumeProfile":
        for item in self.evidence:
            if not item.source.strip():
                raise ValueError(f"Evidence source is required for field {item.field}")
        return self


RESUME_EXTRACTION_PROMPT = """Extract a ResumeProfile from the supplied documents.
Only include facts supported by the source text. Do not invent employers,
dates, achievements, scores, certificates, or skill levels. For every
populated field, add an evidence item with the source file and confidence.
Return JSON matching the ResumeProfile schema.
"""


def parse_resume_profile(value: str | dict[str, Any]) -> ResumeProfile:
    """Validate a model-produced ResumeProfile JSON object."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]) if len(lines) >= 3 else cleaned
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("ResumeProfile response was not valid JSON")
            value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("ResumeProfile must be a JSON object")
    return ResumeProfile.model_validate(value)
