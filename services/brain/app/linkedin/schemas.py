from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LinkedInPostRequest(BaseModel):
    text: str = ""


class LinkedInPostReceipt(BaseModel):
    provider: str
    post_id: str
    permalink: str | None = None
    posted_at: datetime = Field(default_factory=utc_now)
    verified: bool
    evidence: list[str] = Field(default_factory=list)


class LinkedInConnectRequest(BaseModel):
    #: LinkedIn is OAuth 2.0 access-token based — connecting here is a
    #: token paste (the caller having already obtained one via LinkedIn's
    #: own OAuth consent screen), the same self-service shape Instagram
    #: uses for its long-lived Page access token, not a full in-app
    #: OAuth redirect dance.
    access_token: str
