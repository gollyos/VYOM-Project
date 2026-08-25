from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class YouTubePrivacyStatus(str):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class YouTubeUploadRequest(BaseModel):
    video_path: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"  # "People & Blogs" — YouTube's generic default
    privacy_status: str = "private"  # private by default — never auto-public


class YouTubeUploadReceipt(BaseModel):
    provider: str
    video_id: str
    url: str
    uploaded_at: datetime = Field(default_factory=utc_now)
    privacy_status: str
    verified: bool
    evidence: list[str] = Field(default_factory=list)
