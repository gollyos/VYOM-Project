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


class InstagramMessageRequest(BaseModel):
    #: The Instagram-Scoped ID (IGSID) of the recipient — the id Meta
    #: assigns per-user-per-your-account, NOT their @username. It comes
    #: from a webhook payload or the Conversations API; there is no way
    #: to look it up from a username alone (Meta does not expose that
    #: mapping). Sending outside a 24h customer-service window (i.e. the
    #: user hasn't messaged your account recently) is rejected by Meta.
    recipient_id: str
    text: str


class InstagramMessageReceipt(BaseModel):
    provider: str
    message_id: str
    recipient_id: str
    sent_at: datetime = Field(default_factory=utc_now)
    verified: bool


class InstagramConnectRequest(BaseModel):
    instagram_business_account_id: str
    access_token: str
