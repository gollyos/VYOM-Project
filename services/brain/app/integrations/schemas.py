from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"
    REAUTH_REQUIRED = "reauth_required"


class IntegrationRecord(BaseModel):
    id: str
    name: str
    provider: str
    category: str
    enabled: bool = False
    status: IntegrationStatus = IntegrationStatus.DISCONNECTED
    capabilities: set[str] = Field(default_factory=set)
    account_label: str | None = None
    last_health_check: datetime | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class OAuthStart(BaseModel):
    authorization_url: str
    state: str


class OAuthCallback(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=8, max_length=512)
