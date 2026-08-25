from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import YouTubeUploadRequest, YouTubeUploadReceipt


YOUTUBE_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",)

_UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubeProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def upload(self, request: YouTubeUploadRequest) -> YouTubeUploadReceipt: ...


class DisconnectedYouTubeProvider(YouTubeProvider):
    id = "youtube.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "YouTube integration is disconnected"

    async def upload(self, request: YouTubeUploadRequest) -> YouTubeUploadReceipt:
        raise RuntimeError("YouTube integration is disconnected")


class RealYouTubeProvider(DisconnectedYouTubeProvider):
    """Real YouTube upload over the Data API v3's RESUMABLE upload
    protocol (two requests: initiate with metadata, then PUT the actual
    file bytes) — reuses the same GoogleOAuthClient/secret-vault pattern
    as GmailProvider/GoogleSheetsProvider in this repo."""

    id = "youtube"

    def __init__(self, oauth_client, vault) -> None:
        self.oauth_client = oauth_client
        self.vault = vault
        self._client: httpx.AsyncClient | None = None
        self._pending_state: str | None = None

    async def begin_oauth(self, state: str) -> str:
        self._pending_state = state
        return self.oauth_client.authorization_url(state)

    async def complete_oauth(self, code: str) -> dict[str, Any]:
        state = self._pending_state or ""
        self._pending_state = None
        return await self.oauth_client.exchange_code(state, code)

    async def disconnect(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _load_token(self) -> dict[str, Any] | None:
        raw = self.vault.get("oauth:youtube")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def _access_token(self) -> str:
        token = self._load_token()
        if token is None:
            raise RuntimeError("YouTube is not connected — complete OAuth first")
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        if not access_token and refresh_token:
            refreshed = await self.oauth_client.refresh(refresh_token)
            refreshed.setdefault("refresh_token", refresh_token)
            self.vault.set("oauth:youtube", json.dumps(refreshed).encode("utf-8"))
            return refreshed["access_token"]
        if not access_token:
            raise RuntimeError("YouTube token is missing an access_token — reconnect required")
        return access_token

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def health(self) -> tuple[bool, str | None]:
        if self._load_token() is None:
            return False, "YouTube is not connected"
        try:
            access_token = await self._access_token()
            response = await self._pooled().get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except Exception as error:
            return False, f"YouTube health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, f"YouTube returned HTTP {response.status_code}"
        return True, None

    async def upload(self, request: YouTubeUploadRequest) -> YouTubeUploadReceipt:
        video_path = Path(request.video_path)
        if not video_path.exists():
            raise RuntimeError(f"Video file does not exist: {video_path}")
        access_token = await self._access_token()
        metadata = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": request.tags,
                "categoryId": request.category_id,
            },
            "status": {"privacyStatus": request.privacy_status},
        }
        file_size = video_path.stat().st_size
        # Step 1: initiate a resumable upload session — returns a
        # session-specific upload URL in the Location header.
        init_response = await self._pooled().post(
            _UPLOAD_INIT_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
            json=metadata,
        )
        if init_response.status_code >= 400:
            raise RuntimeError(
                f"YouTube upload initiation failed: HTTP {init_response.status_code}: "
                f"{init_response.text[:300]}"
            )
        upload_url = init_response.headers.get("Location")
        if not upload_url:
            raise RuntimeError("YouTube did not return a resumable upload URL")
        # Step 2: PUT the actual video bytes to the session URL.
        video_bytes = video_path.read_bytes()
        upload_response = await self._pooled().put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(file_size)},
            content=video_bytes,
        )
        if upload_response.status_code >= 400:
            raise RuntimeError(
                f"YouTube upload failed: HTTP {upload_response.status_code}: {upload_response.text[:300]}"
            )
        data = upload_response.json()
        video_id = data["id"]
        return YouTubeUploadReceipt(
            provider=self.id, video_id=video_id, url=f"https://youtu.be/{video_id}",
            privacy_status=request.privacy_status, verified=True,
            evidence=[f"provider_video_id:{video_id}", f"file_size_bytes:{file_size}"],
        )
