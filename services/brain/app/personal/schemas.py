from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PreferenceSource(str, Enum):
    USER_STATEMENT = "user_statement"
    INFERRED = "inferred"
    DEFAULT = "default"


class PersonalProfileField(BaseModel):
    """Every learned field carries provenance so a stale observation is
    never presented as a current fact without revalidation (rule 47)."""

    value: Any
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: PreferenceSource = PreferenceSource.USER_STATEMENT
    last_confirmed: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    superseded_value: Any = None

    def is_stale(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or utc_now()) > self.expires_at


class PersonalProfile(BaseModel):
    id: str = "default"
    fields: dict[str, PersonalProfileField] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def get(self, key: str) -> PersonalProfileField | None:
        return self.fields.get(key)

    def set(self, key: str, value: Any, *, source: PreferenceSource = PreferenceSource.USER_STATEMENT, confidence: float = 1.0, expiry_days: int | None = None) -> PersonalProfileField:
        """Supersedes any existing value (rule 48) — the old value is kept
        as `superseded_value` for one generation rather than silently
        discarded, but is never treated as current again."""
        now = utc_now()
        existing = self.fields.get(key)
        field = PersonalProfileField(
            value=value, confidence=confidence, source=source, last_confirmed=now,
            expires_at=(now + timedelta(days=expiry_days)) if expiry_days else None,
            superseded_value=existing.value if existing else None,
        )
        self.fields[key] = field
        self.updated_at = now
        return field


class CommitmentSource(str, Enum):
    EXPLICIT_PROMISE = "explicit_promise"
    MEETING_ACTION_ITEM = "meeting_action_item"
    EMAIL_COMMITMENT = "email_commitment"
    CLIENT_AGREEMENT = "client_agreement"
    TASK_ASSIGNMENT = "task_assignment"


class CommitmentStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class Commitment(BaseModel):
    id: str = Field(default_factory=lambda: f"commitment_{uuid4().hex}")
    description: str
    owner: str = "user"
    recipient: str | None = None
    deadline: datetime | None = None
    source: CommitmentSource = CommitmentSource.EXPLICIT_PROMISE
    status: CommitmentStatus = CommitmentStatus.OPEN
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def is_overdue(self, *, now: datetime | None = None) -> bool:
        if self.status != CommitmentStatus.OPEN or self.deadline is None:
            return False
        return (now or utc_now()) > self.deadline
