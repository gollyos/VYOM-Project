from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramChat(BaseModel):
    chat_id: str
    title: str | None = None
    type: str = "private"


class TelegramMessage(BaseModel):
    message_id: str
    chat_id: str
    text: str
    sender_name: str | None = None
    sent_at: datetime = Field(default_factory=utc_now)


class SendMessageRequest(BaseModel):
    chat_id: str
    text: str
    parse_mode: str | None = None  # "Markdown" / "HTML" / None


class SendReceipt(BaseModel):
    provider: str
    message_id: str
    chat_id: str
    sent_at: datetime
    verified: bool
