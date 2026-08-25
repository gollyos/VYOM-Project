"""Tests for the Instagram posting integration added this session: the
real two-step Meta Graph API content-publishing flow (create container,
then publish it), connected via a long-lived access token + IG Business
Account ID (own-account posting — no App Review needed). Uses
httpx.MockTransport against realistically-shaped Graph API responses.
"""
from __future__ import annotations

import httpx
import pytest

from app.instagram.provider import DisconnectedInstagramProvider, RealInstagramProvider
from app.instagram.schemas import InstagramMessageRequest, InstagramPostRequest
from app.instagram.service import InstagramService
from app.integrations.secrets import InMemorySecretVault


def _connected_provider() -> RealInstagramProvider:
    provider = RealInstagramProvider(InMemorySecretVault())
    provider.store_credentials("17841400000000000", "fake-long-lived-token")
    return provider


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealInstagramProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_when_account_lookup_succeeds():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "17841400000000000" in str(request.url)
        return httpx.Response(200, json={"id": "17841400000000000", "username": "vyom_test"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_health_reports_friendly_error_on_bad_token():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is False
    assert "Invalid OAuth access token" in error


@pytest.mark.asyncio
async def test_post_image_performs_real_two_step_publish_flow():
    provider = _connected_provider()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url)})
        if "/media_publish" in str(request.url):
            return httpx.Response(200, json={"id": "17900000000000001"})
        if request.url.path.endswith("/media"):
            body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
            assert "image_url" in body
            return httpx.Response(200, json={"id": "container_abc123"})
        if request.method == "GET":  # permalink lookup
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/ABC123/"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = InstagramPostRequest(media_url="https://example.com/photo.jpg", caption="Hello VYOM")
    receipt = await provider.post(request)

    assert receipt.verified is True
    assert receipt.media_id == "17900000000000001"
    assert receipt.permalink == "https://www.instagram.com/p/ABC123/"


@pytest.mark.asyncio
async def test_post_reel_uses_video_url_field():
    provider = _connected_provider()
    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media") and request.method == "POST":
            body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
            seen_body.update(body)
            return httpx.Response(200, json={"id": "container_reel"})
        if "/media_publish" in str(request.url):
            return httpx.Response(200, json={"id": "reel_media_id"})
        return httpx.Response(200, json={"permalink": None})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = InstagramPostRequest(
        media_url="https://example.com/video.mp4", media_type="REELS", caption="A reel",
    )
    receipt = await provider.post(request)
    assert receipt.verified is True
    assert "video_url" in seen_body


@pytest.mark.asyncio
async def test_post_surfaces_real_container_creation_error_honestly():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Media URL not accessible"}})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = InstagramPostRequest(media_url="https://example.com/private.jpg")
    with pytest.raises(RuntimeError, match="Media URL not accessible"):
        await provider.post(request)


@pytest.mark.asyncio
async def test_service_refuses_post_when_provider_unhealthy():
    service = InstagramService(DisconnectedInstagramProvider())
    request = InstagramPostRequest(media_url="https://example.com/x.jpg")
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.post(request)


def test_disconnect_removes_stored_credentials():
    import asyncio

    provider = _connected_provider()
    assert provider._load_credentials() is not None
    asyncio.run(provider.disconnect())
    assert provider._load_credentials() is None


# -- messaging (DMs) --------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_posts_to_the_messages_endpoint():
    provider = _connected_provider()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url)})
        assert request.url.path.endswith("/messages")
        import json as _json

        body = _json.loads(request.content)
        assert body["recipient"]["id"] == "1234567890"
        assert body["message"]["text"] == "Hello from VYOM"
        return httpx.Response(200, json={"recipient_id": "1234567890", "message_id": "mid.abc123"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = InstagramMessageRequest(recipient_id="1234567890", text="Hello from VYOM")
    receipt = await provider.send_message(request)

    assert receipt.verified is True
    assert receipt.message_id == "mid.abc123"
    assert receipt.recipient_id == "1234567890"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_message_surfaces_real_error_honestly():
    """Regression guard: Meta rejects DMs sent outside the 24h
    customer-service window - this must surface as a real error, not a
    silent no-op or a fabricated success."""
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Message is sent outside of allowed window"}})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = InstagramMessageRequest(recipient_id="1234567890", text="too late")
    with pytest.raises(RuntimeError, match="allowed window"):
        await provider.send_message(request)


@pytest.mark.asyncio
async def test_service_refuses_message_when_provider_unhealthy():
    service = InstagramService(DisconnectedInstagramProvider())
    request = InstagramMessageRequest(recipient_id="123", text="hi")
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.send_message(request)
