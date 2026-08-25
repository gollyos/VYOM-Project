from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import TwitterPostReceipt, TwitterPostRequest


_API = "https://api.twitter.com/2"


class TwitterProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def post(self, request: TwitterPostRequest) -> TwitterPostReceipt: ...


class DisconnectedTwitterProvider(TwitterProvider):
    id = "twitter.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Twitter integration is disconnected"

    async def post(self, request: TwitterPostRequest) -> TwitterPostReceipt:
        raise RuntimeError("Twitter integration is disconnected")


class RealTwitterProvider(DisconnectedTwitterProvider):
    """Real Twitter/X posting over API v2, connected via a single OAuth
    2.0 User Context bearer/access token (self-service paste, same shape
    as Instagram's Page access token) rather than a full three-legged
    OAuth consent flow — posting to YOUR OWN account needs no app
    review, just a token minted for yourself in the X Developer Portal.
    Storage and the disconnect-on-bad-token behaviour mirror
    RealInstagramProvider exactly."""

    id = "twitter"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None

    def store_credentials(self, access_token: str) -> None:
        self.vault.set("token:twitter", access_token.encode("utf-8"))

    def _load_access_token(self) -> str | None:
        raw = self.vault.get("token:twitter")
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:twitter")
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def health(self) -> tuple[bool, str | None]:
        access_token = self._load_access_token()
        if access_token is None:
            return False, "Twitter is not connected"
        try:
            response = await self._pooled().get(
                f"{_API}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except Exception as error:
            return False, f"Twitter health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, self._friendly_error(response)
        return True, None

    @staticmethod
    def _friendly_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            detail = data.get("detail") or data.get("title") or ""
            if not detail and data.get("errors"):
                detail = data["errors"][0].get("message", "")
        except Exception:
            detail = response.text[:200]
        return f"Twitter rejected the request: {detail}"[:300] or f"HTTP {response.status_code}"

    async def post(self, request: TwitterPostRequest) -> TwitterPostReceipt:
        access_token = self._load_access_token()
        if access_token is None:
            raise RuntimeError("Twitter is not connected")

        response = await self._pooled().post(
            f"{_API}/tweets",
            json={"text": request.text},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Twitter post failed: {self._friendly_error(response)}")
        tweet_id = response.json()["data"]["id"]

        # X has no permalink endpoint on the free tier — the canonical
        # web URL is constructible directly from the tweet id (works for
        # any account, unlike Instagram's permalink which needs a
        # dedicated follow-up API call).
        permalink = f"https://twitter.com/i/web/status/{tweet_id}"

        return TwitterPostReceipt(
            provider=self.id, tweet_id=tweet_id, permalink=permalink, verified=True,
            evidence=[f"provider_tweet_id:{tweet_id}"],
        )
