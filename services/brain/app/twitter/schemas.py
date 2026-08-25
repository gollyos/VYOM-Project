from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TwitterPostRequest(BaseModel):
    text: str


class TwitterPostReceipt(BaseModel):
    provider: str
    tweet_id: str
    permalink: str | None = None
    posted_at: datetime = Field(default_factory=utc_now)
    verified: bool
    evidence: list[str] = Field(default_factory=list)


class TwitterConnectRequest(BaseModel):
    access_token: str
