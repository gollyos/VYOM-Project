from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EmailAddress(BaseModel):
    address: str
    name: str | None = None


class EmailMessage(BaseModel):
    id: str
    thread_id: str
    sender: EmailAddress
    to: list[EmailAddress]
    subject: str
    body_text: str
    received_at: datetime
    labels: list[str] = Field(default_factory=list)
    provider: str


class EmailThread(BaseModel):
    id: str
    subject: str
    participants: list[EmailAddress]
    messages: list[EmailMessage]
    provider: str


class DraftStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    FAILED = "failed"


class EmailDraft(BaseModel):
    id: str = Field(default_factory=lambda: f"draft_{uuid4().hex}")
    thread_id: str | None = None
    to: list[EmailAddress]
    subject: str
    body_text: str
    status: DraftStatus = DraftStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict = Field(default_factory=dict)


class SendReceipt(BaseModel):
    provider: str
    message_id: str
    thread_id: str
    sent_at: datetime
    verified: bool
    evidence: list[str]


class EmailSearchRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=100)


class DraftRequest(BaseModel):
    to: list[EmailAddress]
    subject: str
    body_text: str
    thread_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class SendRequest(BaseModel):
    draft_id: str
    approval_task_id: str | None = None
