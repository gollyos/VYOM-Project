from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DiscordGuild(BaseModel):
    id: str
    name: str


class DiscordSendReceipt(BaseModel):
    provider: str
    message_id: str
    channel_id: str
    sent_at: datetime = Field(default_factory=utc_now)
    verified: bool


class DiscordConnectRequest(BaseModel):
    bot_token: str


class DiscordSendRequest(BaseModel):
    channel_id: str
    content: str
