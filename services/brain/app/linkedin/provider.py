from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import LinkedInPostRequest, LinkedInPostReceipt


_API_BASE = "https://api.linkedin.com/v2"


class LinkedInProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def post(self, request: LinkedInPostRequest) -> LinkedInPostReceipt: ...


class DisconnectedLinkedInProvider(LinkedInProvider):
    id = "linkedin.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "LinkedIn is not connected"

    async def post(self, request: LinkedInPostRequest) -> LinkedInPostReceipt:
        raise RuntimeError("LinkedIn integration is disconnected")


class RealLinkedInProvider(DisconnectedLinkedInProvider):
    """Real LinkedIn posting via a member's OAuth 2.0 access token —
    the caller runs LinkedIn's own OAuth consent screen elsewhere (or
    uses a token issued through LinkedIn's Developer console for their
    own member account) and pastes the resulting access token here,
    mirroring Instagram's long-lived-token connect flow rather than
    VYOM driving a full OAuth redirect dance itself.

    health() doubles as author-identity resolution: LinkedIn's UGC Post
    API requires the author's URN (urn:li:person:{id}), which is only
    obtainable by calling /v2/userinfo with the token — so the same
    call that verifies the token is connected also fetches the URN
    needed later for posting, and the URN is cached to avoid an extra
    round trip on every post.
    """

    id = "linkedin"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None
        self._author_urn: str | None = None

    def store_credentials(self, access_token: str) -> None:
        payload = json.dumps({"access_token": access_token}).encode("utf-8")
        self.vault.set("token:linkedin", payload)
        self._author_urn = None  # a new token may belong to a different member

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("token:linkedin")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:linkedin")
        self._author_urn = None
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
            return False, "LinkedIn is not connected"
        try:
            response = await self._pooled().get(
                f"{_API_BASE}/userinfo",
                headers={"Authorization": f"Bearer {creds['access_token']}"},
            )
        except Exception as error:
            return False, f"LinkedIn health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, self._friendly_error(response)
        sub = response.json().get("sub")
        if not sub:
            return False, "LinkedIn userinfo response did not include a member id"
        self._author_urn = f"urn:li:person:{sub}"
        return True, None

    @staticmethod
    def _friendly_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("message") or data.get("error_description") or ""
        except Exception:
            message = response.text[:200]
        return f"LinkedIn rejected the request: {message}"[:300] or f"HTTP {response.status_code}"

    async def post(self, request: LinkedInPostRequest) -> LinkedInPostReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("LinkedIn is not connected")
        access_token = creds["access_token"]

        # The author URN is only known after a successful health() call
        # (LinkedInService always health-checks before posting), but
        # resolve it defensively here too in case post() is ever called
        # directly against the provider.
        if self._author_urn is None:
            healthy, error = await self.health()
            if not healthy:
                raise RuntimeError(error or "LinkedIn is not connected")

        payload = {
            "author": self._author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": request.text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        response = await self._pooled().post(
            f"{_API_BASE}/ugcPosts",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"LinkedIn post failed: {self._friendly_error(response)}")

        # LinkedIn returns the created post's id in the x-restli-id
        # response header (the JSON body is often empty on success),
        # so the header is the authoritative source, not the body.
        post_id = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
        if not post_id:
            try:
                post_id = response.json().get("id")
            except Exception:
                post_id = None
        if not post_id:
            raise RuntimeError("LinkedIn post succeeded but returned no post id")

        permalink = f"https://www.linkedin.com/feed/update/{post_id}"
        return LinkedInPostReceipt(
            provider=self.id, post_id=post_id, permalink=permalink, verified=True,
            evidence=[f"provider_post_id:{post_id}"],
        )
