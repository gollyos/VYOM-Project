from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import InstagramPostRequest, InstagramPostReceipt


_GRAPH_API = "https://graph.facebook.com/v21.0"


class InstagramProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def post(self, request: InstagramPostRequest) -> InstagramPostReceipt: ...


class DisconnectedInstagramProvider(InstagramProvider):
    id = "instagram.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Instagram integration is disconnected"

    async def post(self, request: InstagramPostRequest) -> InstagramPostReceipt:
        raise RuntimeError("Instagram integration is disconnected")


class RealInstagramProvider(DisconnectedInstagramProvider):
    """Real Instagram posting over the Meta Graph API's two-step content
    publishing flow (create a media container, then publish it) —
    connected via a long-lived Page access token + the account's IG
    Business Account ID, NOT a full OAuth consent flow. This is
    deliberately Meta's own-account posting path (Graph API Explorer /
    a Meta app in Development Mode with yourself as a tester): posting
    to YOUR OWN Instagram Business/Creator account needs no App Review,
    exactly the way this repo's App-Password Gmail path needs no OAuth
    consent screen for the same reason (single account, not a multi-
    tenant SaaS acting on other people's accounts).

    IMPORTANT LIMITATION (Meta's API, not this provider's): Instagram
    fetches media itself from a URL you supply — `media_url` MUST be a
    publicly reachable https URL. A local file path cannot be posted
    directly; the caller uploads it somewhere reachable first (VYOM's
    file/web tools, or any file host) and passes the URL here."""

    id = "instagram"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None

    def store_credentials(self, instagram_business_account_id: str, access_token: str) -> None:
        payload = json.dumps({
            "instagram_business_account_id": instagram_business_account_id,
            "access_token": access_token,
        }).encode("utf-8")
        self.vault.set("token:instagram", payload)

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("token:instagram")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:instagram")
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
            return False, "Instagram is not connected"
        account_id = creds["instagram_business_account_id"]
        try:
            response = await self._pooled().get(
                f"{_GRAPH_API}/{account_id}",
                params={"fields": "id,username", "access_token": creds["access_token"]},
            )
        except Exception as error:
            return False, f"Instagram health check failed: {error}"[:300]
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
        return f"Instagram rejected the request: {message}"[:300] or f"HTTP {response.status_code}"

    async def post(self, request: InstagramPostRequest) -> InstagramPostReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Instagram is not connected")
        account_id = creds["instagram_business_account_id"]
        access_token = creds["access_token"]

        container_params: dict[str, Any] = {"caption": request.caption, "access_token": access_token}
        if request.media_type == "REELS":
            container_params["media_type"] = "REELS"
            container_params["video_url"] = request.media_url
        elif request.media_type == "STORIES":
            container_params["media_type"] = "STORIES"
            container_params["image_url"] = request.media_url
        else:
            container_params["image_url"] = request.media_url

        container_response = await self._pooled().post(f"{_GRAPH_API}/{account_id}/media", data=container_params)
        if container_response.status_code >= 400:
            raise RuntimeError(f"Instagram container creation failed: {self._friendly_error(container_response)}")
        container_id = container_response.json()["id"]

        # Video containers (REELS) process asynchronously server-side;
        # publishing before Meta finishes processing returns a specific,
        # recognisable error rather than succeeding — poll a bounded
        # number of times rather than either guessing a fixed sleep or
        # failing on the very first attempt.
        publish_response = None
        for _attempt in range(6):
            publish_response = await self._pooled().post(
                f"{_GRAPH_API}/{account_id}/media_publish",
                data={"creation_id": container_id, "access_token": access_token},
            )
            if publish_response.status_code < 400:
                break
            body_text = publish_response.text
            if "media id is not available" not in body_text.lower() and "not ready" not in body_text.lower():
                break
            await asyncio.sleep(5)
        if publish_response is None or publish_response.status_code >= 400:
            raise RuntimeError(
                f"Instagram publish failed: {self._friendly_error(publish_response)}"
                if publish_response is not None else "Instagram publish failed with no response"
            )
        media_id = publish_response.json()["id"]

        permalink = None
        try:
            permalink_response = await self._pooled().get(
                f"{_GRAPH_API}/{media_id}", params={"fields": "permalink", "access_token": access_token},
            )
            if permalink_response.status_code < 400:
                permalink = permalink_response.json().get("permalink")
        except Exception:
            pass  # permalink is a nice-to-have; the post itself already succeeded

        return InstagramPostReceipt(
            provider=self.id, media_id=media_id, permalink=permalink, verified=True,
            evidence=[f"provider_media_id:{media_id}", f"container_id:{container_id}"],
        )
