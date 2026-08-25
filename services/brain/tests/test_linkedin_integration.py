"""Tests for the native LinkedIn integration added this session:
OAuth 2.0 access-token based posting (mirrors Instagram's long-lived
access-token connect pattern). Uses httpx.MockTransport throughout —
no real network calls, no real token."""
from __future__ import annotations

import httpx
import pytest

from app.linkedin.provider import DisconnectedLinkedInProvider, RealLinkedInProvider
from app.linkedin.schemas import LinkedInPostRequest
from app.linkedin.service import LinkedInService
from app.schemas.approvals import PermissionLevel
from app.tools_builtin.linkedin_tool import LinkedInTool
from app.tools.errors import ToolValidationError


class _FakeVault:
    """Minimal in-memory stand-in for the Windows-DPAPI SecretStore."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def set(self, key: str, value: bytes) -> None:
        self._data[key] = value

    def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


def _provider_with_transport(handler, vault: _FakeVault | None = None) -> RealLinkedInProvider:
    provider = RealLinkedInProvider(vault or _FakeVault())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    provider = RealLinkedInProvider(_FakeVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_disconnected_provider_health_and_post():
    provider = DisconnectedLinkedInProvider()
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error
    with pytest.raises(RuntimeError):
        await provider.post(LinkedInPostRequest(text="hi"))


@pytest.mark.asyncio
async def test_health_true_and_resolves_author_urn():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/userinfo")
        assert request.headers["Authorization"] == "Bearer good-token"
        return httpx.Response(200, json={"sub": "abc123", "name": "Test Member"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("good-token")
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None
    assert provider._author_urn == "urn:li:person:abc123"


@pytest.mark.asyncio
async def test_health_false_on_401_bad_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid access token"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("bad-token")
    healthy, error = await provider.health()
    assert healthy is False
    assert "rejected" in error.lower()


@pytest.mark.asyncio
async def test_connect_flow_disconnects_on_bad_token_via_api():
    """Mirrors app/api/linkedin.py's connect() behaviour directly
    against the provider: a failed health check after storing
    credentials must roll back (disconnect) and surface a 401-style
    failure to the caller."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid access token"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("bad-token")
    healthy, error = await provider.health()
    assert healthy is False
    await provider.disconnect()
    assert vault.get("token:linkedin") is None


@pytest.mark.asyncio
async def test_post_success_returns_post_id_and_permalink():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": "member42"})
        assert request.url.path.endswith("/ugcPosts")
        body = request.read()
        import json as _json
        payload = _json.loads(body)
        assert payload["author"] == "urn:li:person:member42"
        assert payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareCommentary"]["text"] == "Hello LinkedIn"
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"}, json={})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("good-token")
    service = LinkedInService(provider)
    receipt = await service.post(LinkedInPostRequest(text="Hello LinkedIn"))
    assert receipt.post_id == "urn:li:share:999"
    assert receipt.permalink == "https://www.linkedin.com/feed/update/urn:li:share:999"
    assert receipt.verified is True


@pytest.mark.asyncio
async def test_post_fails_when_provider_unhealthy():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid access token"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("bad-token")
    service = LinkedInService(provider)
    with pytest.raises(RuntimeError, match="rejected"):
        await service.post(LinkedInPostRequest(text="won't post"))


@pytest.mark.asyncio
async def test_post_raises_on_linkedin_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": "member42"})
        return httpx.Response(422, json={"message": "Unsupported media category"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("good-token")
    service = LinkedInService(provider)
    with pytest.raises(RuntimeError, match="Unsupported media category"):
        await service.post(LinkedInPostRequest(text="oops"))


@pytest.mark.asyncio
async def test_tool_permission_is_always_l2():
    tool = LinkedInTool(service=None)
    assert tool.permission_for({}) == PermissionLevel.L2
    assert tool.permission_for({"text": "anything"}) == PermissionLevel.L2
    assert tool.metadata.risk_level == "high"


@pytest.mark.asyncio
async def test_tool_rejects_empty_text():
    tool = LinkedInTool(service=None)
    with pytest.raises(ToolValidationError):
        await tool.execute({"text": "   "}, context=None)


@pytest.mark.asyncio
async def test_tool_execute_posts_and_returns_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": "member42"})
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:555"}, json={})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("good-token")
    service = LinkedInService(provider)
    tool = LinkedInTool(service)
    result = await tool.execute({"text": "Posting via tool"}, context=None)
    assert result.structured_output["post_id"] == "urn:li:share:555"
    assert "linkedin.com/feed/update" in result.structured_output["permalink"]


@pytest.mark.asyncio
async def test_tool_health_reflects_provider_health():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sub": "member42"})

    vault = _FakeVault()
    provider = _provider_with_transport(handler, vault)
    provider.store_credentials("good-token")
    service = LinkedInService(provider)
    tool = LinkedInTool(service)
    health = await tool.health()
    assert health["healthy"] is True
