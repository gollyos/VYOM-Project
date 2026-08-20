from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MeetingBriefing(BaseModel):
    event_id: str
    title: str
    starts_at: datetime
    attendees: list[str]
    context: list[str]
    open_items: list[str]
    source_status: dict[str, str]


class MeetingNotes(BaseModel):
    event_id: str
    notes: str
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


class FollowUpDraft(BaseModel):
    event_id: str
    subject: str
    body: str
    recipients: list[str]
