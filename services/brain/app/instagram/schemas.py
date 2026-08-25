from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramPostRequest(BaseModel):
    #: Instagram fetches the media itself — this MUST be a publicly
    #: reachable https URL, never a local path. See provider docstring.
    media_url: str
    media_type: str = "IMAGE"  # IMAGE | REELS | STORIES
    caption: str = ""


class InstagramPostReceipt(BaseModel):
    provider: str
    media_id: str
    permalink: str | None = None
    posted_at: datetime = Field(default_factory=utc_now)
    verified: bool
    evidence: list[str] = Field(default_factory=list)


class InstagramConnectRequest(BaseModel):
    instagram_business_account_id: str
    access_token: str
