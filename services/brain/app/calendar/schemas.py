from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    attendees: list[str] = Field(default_factory=list)
    location: str | None = None
    provider: str
    status: str = "confirmed"


class AvailabilityRequest(BaseModel):
    start_at: datetime
    end_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    timezone: str = "Asia/Calcutta"


class AvailabilitySlot(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str


class CreateEventRequest(BaseModel):
    title: str
    start_at: datetime
    end_at: datetime
    attendees: list[str] = Field(default_factory=list)
    location: str | None = None
    timezone: str = "Asia/Calcutta"


class CalendarReceipt(BaseModel):
    provider: str
    event_id: str
    verified: bool
    evidence: list[str]
