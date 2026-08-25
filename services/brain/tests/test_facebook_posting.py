"""Tests for the Facebook Page posting integration: text/link posts via
the Graph API /feed endpoint, photo posts via /photos - a SINGLE Graph
API call either way, unlike Instagram's two-step create-container-then-
publish flow (Facebook Pages have no async media processing step for a
plain photo/link/text post). Connected via a long-lived Page access
token + Page ID (own-Page posting - no App Review needed). Uses
httpx.MockTransport against realistically-shaped Graph API responses.
"""
from __future__ import annotations

import httpx
import pytest

from app.facebook.provider import DisconnectedFacebookProvider, RealFacebookProvider
from app.facebook.schemas import FacebookPostRequest
from app.facebook.service import FacebookService
from app.integrations.secrets import InMemorySecretVault


def _connected_provider() -> RealFacebookProvider:
    provider = RealFacebookProvider(InMemorySecretVault())
    provider.store_credentials("100000000000000", "fake-page-token")
    return provider


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealFacebookProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_when_page_lookup_succeeds():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "100000000000000" in str(request.url)
        return httpx.Response(200, json={"id": "100000000000000", "name": "VYOM Test Page"})

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
async def test_post_text_message_uses_feed_endpoint():
    provider = _connected_provider()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url)})
        if request.url.path.endswith("/feed"):
            body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
            assert "message" in body
            return httpx.Response(200, json={"id": "100000000000000_1"})
        if request.method == "GET":  # permalink lookup
            return httpx.Response(200, json={"permalink_url": "https://www.facebook.com/100/posts/1"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = FacebookPostRequest(message="Hello VYOM")
    receipt = await provider.post(request)

    assert receipt.verified is True
    assert receipt.post_id == "100000000000000_1"
    assert receipt.permalink == "https://www.facebook.com/100/posts/1"
    assert any(call["url"].endswith("/feed") for call in calls)


@pytest.mark.asyncio
async def test_post_with_link_includes_link_field():
    provider = _connected_provider()
    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/feed") and request.method == "POST":
            body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
            seen_body.update(body)
            return httpx.Response(200, json={"id": "100000000000000_2"})
        return httpx.Response(200, json={"permalink_url": None})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = FacebookPostRequest(message="Check this out", link="https://example.com")
    receipt = await provider.post(request)
    assert receipt.verified is True
    assert "link" in seen_body


@pytest.mark.asyncio
async def test_post_photo_uses_photos_endpoint_not_feed():
    """A photo post is a genuinely different Graph API endpoint from a
    text/link post - this is the regression the test guards against."""
    provider = _connected_provider()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/photos"):
            body = dict(x.split("=") for x in request.content.decode().split("&") if "=" in x)
            assert "url" in body
            return httpx.Response(200, json={"id": "photo_1", "post_id": "100000000000000_3"})
        return httpx.Response(200, json={"permalink_url": None})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = FacebookPostRequest(message="A photo", photo_url="https://example.com/photo.jpg")
    receipt = await provider.post(request)

    assert receipt.verified is True
    assert receipt.post_id == "100000000000000_3"  # uses the post_id from /photos, not the photo's own id
    assert any(path.endswith("/photos") for path in calls)
    assert not any(path.endswith("/feed") for path in calls)


@pytest.mark.asyncio
async def test_post_surfaces_real_graph_api_error_honestly():
    provider = _connected_provider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Message is empty"}})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = FacebookPostRequest(message="")
    with pytest.raises(RuntimeError, match="Message is empty"):
        await provider.post(request)


@pytest.mark.asyncio
async def test_service_refuses_post_when_provider_unhealthy():
    service = FacebookService(DisconnectedFacebookProvider())
    request = FacebookPostRequest(message="hello")
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.post(request)


def test_disconnect_removes_stored_credentials():
    import asyncio

    provider = _connected_provider()
    assert provider._load_credentials() is not None
    asyncio.run(provider.disconnect())
    assert provider._load_credentials() is None
