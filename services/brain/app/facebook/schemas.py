from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FacebookPostRequest(BaseModel):
    #: Text-only, link, or photo post. Facebook's Page /feed endpoint
    #: accepts message + an optional link (Facebook fetches its own
    #: preview) or a photo URL (posted via /photos instead — see
    #: provider). Facebook, unlike Instagram, does NOT require the
    #: image to already be public if posted as a raw file, but this
    #: provider always uses the URL-based path for consistency with
    #: Instagram's model and to avoid a second file-upload code path.
    message: str = ""
    link: str | None = None
    photo_url: str | None = None


class FacebookPostReceipt(BaseModel):
    provider: str
    post_id: str
    permalink: str | None = None
    posted_at: datetime = Field(default_factory=utc_now)
    verified: bool
    evidence: list[str] = Field(default_factory=list)


class FacebookConnectRequest(BaseModel):
    #: A Facebook PAGE (not a personal profile - the Graph API does not
    #: allow posting to personal timelines for apps, only to Pages) plus
    #: a Page access token. Same connect shape as Instagram: a long-lived
    #: Page token from the Graph API Explorer, no App Review needed for
    #: posting to a Page you administer.
    page_id: str
    access_token: str
