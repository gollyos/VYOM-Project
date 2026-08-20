from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactType(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"
    SPREADSHEET = "spreadsheet"
    CSV = "csv"
    PRESENTATION = "presentation"
    DIAGRAM = "diagram"
    JSON = "json"


class ArtifactStatus(str, Enum):
    DRAFT = "draft"
    RENDERED = "rendered"
    VALIDATED = "validated"
    FAILED = "failed"
    FINAL = "final"


class ContentSection(BaseModel):
    heading: str
    body: str = ""
    bullets: list[str] = Field(default_factory=list)
    table: dict[str, Any] | None = None


class ArtifactSpec(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex}")
    type: ArtifactType
    title: str
    purpose: str = ""
    audience: str = "internal"
    content_sections: list[ContentSection] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    style: str = "neutral-professional"
    branding: dict[str, Any] = Field(default_factory=dict)
    verification_requirements: list[str] = Field(default_factory=list)
    output_path: str | None = None
    created_by: str = "artifact-engine"
    task_id: str | None = None
    version: str = "v1"


class ArtifactRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex}")
    spec: ArtifactSpec
    status: ArtifactStatus = ArtifactStatus.DRAFT
    output_path: str | None = None
    version: str = "v1"
    versions: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    verified: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
