"""Tests for the native Twitter/X integration, mirroring Instagram's
access-token connect/post pattern. Uses httpx.MockTransport injected
into RealTwitterProvider's pooled client so connect/health/post never
touch the real network — there is no real Twitter API token configured
anywhere in this repo.
"""
from __future__ import annotations

import httpx
import pytest

from app.integrations.secrets import InMemorySecretVault
from app.schemas.approvals import PermissionLevel
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools_builtin.twitter_tool import TwitterTool
from app.twitter.provider import DisconnectedTwitterProvider, RealTwitterProvider
from app.twitter.schemas import TwitterPostRequest
from app.twitter.service import TwitterService


def _provider_with_transport(handler, token: str | None = "fake-bearer-token") -> RealTwitterProvider:
    provider = RealTwitterProvider(InMemorySecretVault())
    if token is not None:
        provider.store_credentials(token)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def _dummy_context() -> ToolContext:
    return ToolContext(task_id="t1", permission_level=PermissionLevel.L2, allowed_roots=())


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealTwitterProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_on_valid_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/users/me"
        assert request.headers["Authorization"] == "Bearer fake-bearer-token"
        return httpx.Response(200, json={"data": {"id": "123", "username": "vyom_bot"}})

    provider = _provider_with_transport(handler)
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_health_false_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid token"})

    provider = _provider_with_transport(handler)
    healthy, error = await provider.health()
    assert healthy is False
    assert "rejected" in error.lower()


@pytest.mark.asyncio
async def test_connect_success_reports_connected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"id": "123", "username": "vyom_bot"}})

    provider = _provider_with_transport(handler, token=None)
    provider.store_credentials("good-token")
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_connect_bad_token_fails_health_and_disconnects():
    """Mirrors app/api/twitter.py's connect endpoint: store creds, run a
    real health() check, and disconnect + raise 401 if it fails."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid token"})

    provider = _provider_with_transport(handler, token=None)
    provider.store_credentials("bad-token")
    healthy, error = await provider.health()
    assert healthy is False
    if not healthy:
        await provider.disconnect()
    # After disconnect, credentials are gone and health reports not-connected.
    healthy_after, error_after = await provider.health()
    assert healthy_after is False
    assert "not connected" in error_after


@pytest.mark.asyncio
async def test_post_success_returns_receipt_with_id_and_permalink():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "123", "username": "vyom_bot"}})
        assert request.url.path == "/2/tweets"
        assert request.headers["Authorization"] == "Bearer fake-bearer-token"
        body = request.content.decode("utf-8")
        assert "hello world" in body
        return httpx.Response(201, json={"data": {"id": "9999999999", "text": "hello world"}})

    provider = _provider_with_transport(handler)
    service = TwitterService(provider)
    receipt = await service.post(TwitterPostRequest(text="hello world"))
    assert receipt.tweet_id == "9999999999"
    assert receipt.permalink == "https://twitter.com/i/web/status/9999999999"
    assert receipt.verified is True


@pytest.mark.asyncio
async def test_post_fails_when_provider_unhealthy():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"title": "Unauthorized"})

    provider = _provider_with_transport(handler)
    service = TwitterService(provider)
    with pytest.raises(RuntimeError):
        await service.post(TwitterPostRequest(text="hello"))


@pytest.mark.asyncio
async def test_post_raises_on_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "123"}})
        return httpx.Response(400, json={"title": "Bad Request", "detail": "text too long"})

    provider = _provider_with_transport(handler)
    service = TwitterService(provider)
    with pytest.raises(RuntimeError, match="text too long"):
        await service.post(TwitterPostRequest(text="hello"))


@pytest.mark.asyncio
async def test_disconnected_provider_reports_unhealthy_and_raises_on_post():
    provider = DisconnectedTwitterProvider()
    healthy, error = await provider.health()
    assert healthy is False
    assert "disconnected" in error
    with pytest.raises(RuntimeError):
        await provider.post(TwitterPostRequest(text="hello"))


# --- TwitterTool (BaseTool wrapper) ---------------------------------------


@pytest.mark.asyncio
async def test_tool_permission_is_always_l2():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"id": "123"}})

    provider = _provider_with_transport(handler)
    tool = TwitterTool(TwitterService(provider))
    assert tool.permission_for({}) == PermissionLevel.L2
    assert tool.permission_for({"text": "anything"}) == PermissionLevel.L2
    assert tool.metadata.risk_level == "high"


@pytest.mark.asyncio
async def test_tool_rejects_empty_text():
    provider = _provider_with_transport(lambda r: httpx.Response(200, json={"data": {"id": "1"}}))
    tool = TwitterTool(TwitterService(provider))
    with pytest.raises(ToolValidationError):
        await tool.execute({"text": ""}, _dummy_context())
    with pytest.raises(ToolValidationError):
        await tool.execute({"text": "   "}, _dummy_context())


@pytest.mark.asyncio
async def test_tool_rejects_text_over_280_chars():
    provider = _provider_with_transport(lambda r: httpx.Response(200, json={"data": {"id": "1"}}))
    tool = TwitterTool(TwitterService(provider))
    with pytest.raises(ToolValidationError):
        await tool.execute({"text": "x" * 281}, _dummy_context())


@pytest.mark.asyncio
async def test_tool_accepts_text_at_280_chars_and_posts():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "123"}})
        return httpx.Response(201, json={"data": {"id": "42"}})

    provider = _provider_with_transport(handler)
    tool = TwitterTool(TwitterService(provider))
    result = await tool.execute({"text": "x" * 280}, _dummy_context())
    assert result.structured_output["tweet_id"] == "42"
    assert result.structured_output["permalink"] == "https://twitter.com/i/web/status/42"


@pytest.mark.asyncio
async def test_tool_health_reflects_provider_health():
    provider = _provider_with_transport(lambda r: httpx.Response(200, json={"data": {"id": "1"}}))
    tool = TwitterTool(TwitterService(provider))
    health = await tool.health()
    assert health["healthy"] is True

    bad_provider = _provider_with_transport(lambda r: httpx.Response(401, json={"title": "Unauthorized"}))
    bad_tool = TwitterTool(TwitterService(bad_provider))
    bad_health = await bad_tool.health()
    assert bad_health["healthy"] is False
