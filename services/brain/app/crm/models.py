from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LeadState(str, Enum):
    NEW = "new"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING = "meeting"
    PROPOSAL = "proposal"
    WON = "won"
    LOST = "lost"
    DO_NOT_CONTACT = "do_not_contact"


class CRMRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"crm_{uuid4().hex}")
    record_type: str
    name: str
    normalized_key: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Lead(CRMRecord):
    record_type: str = "lead"
    company: str
    domain: str
    contact_name: str | None = None
    contact_email: str | None = None
    state: LeadState = LeadState.NEW
    score: int = Field(default=0, ge=0, le=100)
    qualification_reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    do_not_contact: bool = False


class Client(CRMRecord):
    record_type: str = "client"
    domain: str | None = None
    status: str = "active"
    owner: str | None = None


class Person(CRMRecord):
    record_type: str = "person"
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    company_id: str | None = None


class Opportunity(CRMRecord):
    record_type: str = "opportunity"
    client_id: str | None = None
    stage: str = "discovery"
    value: float | None = None
    currency: str = "USD"


class Project(CRMRecord):
    record_type: str = "project"
    client_id: str | None = None
    status: str = "active"


class Campaign(CRMRecord):
    record_type: str = "campaign"
    channel: str
    status: str = "draft"


class Interaction(CRMRecord):
    record_type: str = "interaction"
    subject_id: str
    channel: str
    direction: str
    summary: str
    occurred_at: datetime = Field(default_factory=utc_now)
    evidence: list[str] = Field(default_factory=list)


class ActivityRecord(CRMRecord):
    record_type: str = "activity"
    action: str
    subject_id: str
    actor: str
    evidence: list[str] = Field(default_factory=list)
