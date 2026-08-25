from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppStatus(BaseModel):
    state: str  # disconnected | starting | qr_pending | authenticated | ready | auth_failure
    qr_data_url: str | None = None
    pushname: str | None = None
    wid: str | None = None
    detail: str | None = None


class WhatsAppSendRequest(BaseModel):
    to: str  # e.g. "919876543210" or "919876543210@c.us"
    body: str
