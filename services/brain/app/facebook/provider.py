from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import FacebookPostReceipt, FacebookPostRequest


_GRAPH_API = "https://graph.facebook.com/v21.0"


class FacebookProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def post(self, request: FacebookPostRequest) -> FacebookPostReceipt: ...


class DisconnectedFacebookProvider(FacebookProvider):
    id = "facebook.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Facebook integration is disconnected"

    async def post(self, request: FacebookPostRequest) -> FacebookPostReceipt:
        raise RuntimeError("Facebook integration is disconnected")


class RealFacebookProvider(DisconnectedFacebookProvider):
    """Real Facebook Page posting over the Meta Graph API's /feed
    endpoint (text/link posts) or /photos endpoint (photo posts) — a
    SINGLE API call, unlike Instagram's create-container-then-publish
    flow, because Facebook Pages don't have Instagram's async media
    processing step for a plain photo/link/text post.

    Connected via a long-lived PAGE access token + Page ID (Graph API
    Explorer, or a Meta app in Development Mode with yourself as
    Page admin) — same self-account posting path as this repo's
    Instagram provider, no App Review needed for posting to your own
    Page."""

    id = "facebook"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None

    def store_credentials(self, page_id: str, access_token: str) -> None:
        payload = json.dumps({"page_id": page_id, "access_token": access_token}).encode("utf-8")
        self.vault.set("token:facebook", payload)

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("token:facebook")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:facebook")
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def health(self) -> tuple[bool, str | None]:
        creds = self._load_credentials()
        if creds is None:
            return False, "Facebook is not connected"
        page_id = creds["page_id"]
        try:
            response = await self._pooled().get(
                f"{_GRAPH_API}/{page_id}",
                params={"fields": "id,name", "access_token": creds["access_token"]},
            )
        except Exception as error:
            return False, f"Facebook health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, self._friendly_error(response)
        return True, None

    @staticmethod
    def _friendly_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("error", {}).get("message", "")
        except Exception:
            message = response.text[:200]
        return f"Facebook rejected the request: {message}"[:300] or f"HTTP {response.status_code}"

    async def post(self, request: FacebookPostRequest) -> FacebookPostReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Facebook is not connected")
        page_id = creds["page_id"]
        access_token = creds["access_token"]

        # A photo post goes through /photos (which also accepts a
        # caption via `message`); a text/link post goes through /feed.
        # These are genuinely different Graph API endpoints, not just
        # different parameters on one call.
        if request.photo_url:
            params: dict[str, Any] = {
                "url": request.photo_url, "caption": request.message, "access_token": access_token,
            }
            response = await self._pooled().post(f"{_GRAPH_API}/{page_id}/photos", data=params)
        else:
            params = {"message": request.message, "access_token": access_token}
            if request.link:
                params["link"] = request.link
            response = await self._pooled().post(f"{_GRAPH_API}/{page_id}/feed", data=params)

        if response.status_code >= 400:
            raise RuntimeError(f"Facebook post failed: {self._friendly_error(response)}")
        body = response.json()
        # /photos returns {"id": "<photo_id>", "post_id": "<post_id>"};
        # /feed returns {"id": "<post_id>"} directly.
        post_id = body.get("post_id") or body["id"]

        permalink = None
        try:
            permalink_response = await self._pooled().get(
                f"{_GRAPH_API}/{post_id}", params={"fields": "permalink_url", "access_token": access_token},
            )
            if permalink_response.status_code < 400:
                permalink = permalink_response.json().get("permalink_url")
        except Exception:
            pass  # permalink is a nice-to-have; the post itself already succeeded

        return FacebookPostReceipt(
            provider=self.id, post_id=post_id, permalink=permalink, verified=True,
            evidence=[f"provider_post_id:{post_id}"],
        )
