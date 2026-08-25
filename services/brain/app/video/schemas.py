from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VideoStatus(str, Enum):
    DRAFT = "draft"
    RENDERING = "rendering"
    RENDERED = "rendered"
    FAILED = "failed"


class VideoScene(BaseModel):
    """One scene: narration text (spoken via TTS) shown over one still
    image for the duration the narration actually takes to speak — not a
    guessed/fixed duration, the REAL measured length of the rendered
    audio clip."""

    text: str
    image_path: str | None = None
    image_prompt: str | None = None
    duration_seconds: float | None = None
    audio_path: str | None = None


class VideoCreateRequest(BaseModel):
    title: str
    scenes: list[VideoScene] = Field(default_factory=list)
    voice: str = "en-US-AriaNeural"
    resolution: str = "1280x720"
    fps: int = 30
    aspect_ratio: str = "16:9"


class VideoJob(BaseModel):
    id: str = Field(default_factory=lambda: f"video_{uuid4().hex[:16]}")
    title: str
    status: VideoStatus = VideoStatus.DRAFT
    scenes: list[VideoScene] = Field(default_factory=list)
    output_path: str | None = None
    duration_seconds: float | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    voice: str = "en-US-AriaNeural"
    resolution: str = "1280x720"
    fps: int = 30
