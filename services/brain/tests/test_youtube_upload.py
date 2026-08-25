"""Tests for the YouTube upload integration added this session: real
resumable-upload protocol (two requests — initiate with metadata, then
PUT the file bytes) over the same GoogleOAuthClient/secret-vault pattern
as GmailProvider/GoogleSheetsProvider. Uses httpx.MockTransport against
realistically-shaped YouTube Data API v3 responses (same pattern as
test_google_workspace_integrations.py).
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.secrets import InMemorySecretVault
from app.youtube.provider import DisconnectedYouTubeProvider, RealYouTubeProvider
from app.youtube.schemas import YouTubeUploadRequest
from app.youtube.service import YouTubeService


class _FakeOAuthClient:
    def __init__(self):
        self.refreshed = False

    def authorization_url(self, state: str) -> str:
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    async def exchange_code(self, state: str, code: str) -> dict:
        return {"access_token": "fake-access-token", "refresh_token": "fake-refresh-token", "token_type": "Bearer"}

    async def refresh(self, refresh_token: str) -> dict:
        self.refreshed = True
        return {"access_token": "refreshed-access-token", "token_type": "Bearer"}


def _connected_provider(vault=None) -> RealYouTubeProvider:
    vault = vault or InMemorySecretVault()
    provider = RealYouTubeProvider(_FakeOAuthClient(), vault)
    vault.set("oauth:youtube", json.dumps({
        "access_token": "fake-access-token", "refresh_token": "fake-refresh-token",
    }).encode("utf-8"))
    return provider


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealYouTubeProvider(_FakeOAuthClient(), InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_when_channel_lookup_succeeds():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "channels" in str(request.url)
        assert request.headers["Authorization"] == "Bearer fake-access-token"
        return httpx.Response(200, json={"items": [{"id": "UC_test_channel"}]})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_upload_performs_real_two_step_resumable_flow(tmp_path):
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"fake mp4 bytes for testing" * 100)

    provider = _connected_provider()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            assert "uploadType=resumable" in str(request.url)
            body = json.loads(request.content)
            assert body["snippet"]["title"] == "My Test Video"
            assert body["status"]["privacyStatus"] == "private"
            return httpx.Response(
                200, headers={"Location": "https://upload.example.com/session/abc123"},
            )
        if request.method == "PUT":
            assert str(request.url) == "https://upload.example.com/session/abc123"
            assert request.headers["Content-Type"] == "video/mp4"
            return httpx.Response(200, json={"id": "dQw4w9WgXcQ", "kind": "youtube#video"})
        raise AssertionError(f"unexpected method {request.method}")

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = YouTubeUploadRequest(video_path=str(video_file), title="My Test Video")
    receipt = await provider.upload(request)

    assert calls == ["POST", "PUT"]
    assert receipt.verified is True
    assert receipt.video_id == "dQw4w9WgXcQ"
    assert receipt.url == "https://youtu.be/dQw4w9WgXcQ"
    assert receipt.privacy_status == "private"


@pytest.mark.asyncio
async def test_upload_rejects_missing_file():
    provider = _connected_provider()
    request = YouTubeUploadRequest(video_path="/nonexistent/fake/video.mp4", title="Missing file test")
    with pytest.raises(RuntimeError, match="does not exist"):
        await provider.upload(request)


@pytest.mark.asyncio
async def test_upload_surfaces_real_api_error_honestly(tmp_path):
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"fake bytes")

    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='{"error": {"message": "quotaExceeded"}}')

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = YouTubeUploadRequest(video_path=str(video_file), title="Quota test")
    with pytest.raises(RuntimeError, match="quotaExceeded|403"):
        await provider.upload(request)


@pytest.mark.asyncio
async def test_service_refuses_upload_when_provider_unhealthy():
    service = YouTubeService(DisconnectedYouTubeProvider())
    request = YouTubeUploadRequest(video_path="/some/path.mp4", title="Test")
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.upload(request)


@pytest.mark.asyncio
async def test_default_privacy_status_is_private_not_public():
    """A video upload must NEVER default to public — this is the same
    'never auto-public' discipline as email's L2-approval-required send."""
    request = YouTubeUploadRequest(video_path="/x.mp4", title="Test")
    assert request.privacy_status == "private"
