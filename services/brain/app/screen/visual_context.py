from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScreenObservation(BaseModel):
    """Structured screen understanding. `visible_text` and
    `interactive_elements` are only populated when a vision-capable model
    or accessibility text extraction actually enriched this observation --
    VYOM never invents hidden screen content (see docs/SCREEN_UNDERSTANDING.md)."""

    active_application: str | None = None
    active_window: str | None = None
    visible_text: str = ""
    interactive_elements: list[str] = Field(default_factory=list)
    layout_summary: str = ""
    important_regions: list[str] = Field(default_factory=list)
    possible_actions: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    screenshot_path: str | None = None
    redacted_secret_count: int = 0
    captured_at: datetime = Field(default_factory=utc_now)
