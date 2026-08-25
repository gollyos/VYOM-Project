"""Tests for the native Discord bot integration: the real Discord Bot API
provider (RealDiscordProvider), the thin service layer built on top of it,
the DiscordTool permission tiers, and the REST connect/disconnect/status/
send endpoints. Uses httpx.MockTransport against realistically-shaped
Discord API v10 responses — never a real network call, matching the house
rule that there is no keyless Discord API to hit in CI.
"""
from __future__ import annotations

import httpx
import pytest

from app.integrations.secrets import InMemorySecretVault
from app.messaging.discord_provider import DisconnectedDiscordProvider, MockDiscordProvider, RealDiscordProvider
from app.messaging.discord_schemas import DiscordGuild
from app.messaging.discord_service import DiscordService
from app.tools.errors import ToolValidationError
from app.tools_builtin.discord_tool import DiscordTool


def _provider_with_token(vault: InMemorySecretVault, token: str = "fake-bot-token") -> RealDiscordProvider:
    provider = RealDiscordProvider(vault)
    provider.store_credentials(token)
    return provider


@pytest.mark.asyncio
async def test_real_provider_health_ok_when_users_me_succeeds():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/users/@me" in str(request.url)
        assert request.headers["authorization"] == "Bot fake-bot-token"
        return httpx.Response(200, json={"id": "1", "username": "vyom_bot"})

    provider = _provider_with_token(InMemorySecretVault())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None
    await provider.disconnect()


@pytest.mark.asyncio
async def test_real_provider_health_reports_bad_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized", "code": 0})

    provider = _provider_with_token(InMemorySecretVault(), token="bad-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is False
    assert "Unauthorized" in error
    await provider.disconnect()


@pytest.mark.asyncio
async def test_health_reports_not_connected_when_no_credentials():
    provider = RealDiscordProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_send_message_builds_correct_discord_api_call():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        assert "/channels/999/messages" in str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "42", "channel_id": "999", "content": "hi there"})

    provider = _provider_with_token(InMemorySecretVault())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    receipt = await provider.send_message("999", "hi there")

    assert receipt.message_id == "42"
    assert receipt.channel_id == "999"
    assert receipt.verified is True
    assert captured["body"]["content"] == "hi there"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_send_message_raises_clear_error_on_api_rejection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Missing Access", "code": 50001})

    provider = _provider_with_token(InMemorySecretVault())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="Missing Access"):
        await provider.send_message("doesnotexist", "hi")
    await provider.disconnect()


@pytest.mark.asyncio
async def test_list_guilds_parses_real_shaped_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/users/@me/guilds" in str(request.url)
        return httpx.Response(200, json=[
            {"id": "111", "name": "VYOM HQ", "owner": False},
            {"id": "222", "name": "Test Server", "owner": True},
        ])

    provider = _provider_with_token(InMemorySecretVault())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    guilds = await provider.list_guilds()

    assert len(guilds) == 2
    assert guilds[0] == DiscordGuild(id="111", name="VYOM HQ")
    await provider.disconnect()


@pytest.mark.asyncio
async def test_disconnected_provider_fails_closed_on_every_operation():
    provider = DisconnectedDiscordProvider()
    healthy, error = await provider.health()
    assert healthy is False
    with pytest.raises(RuntimeError):
        await provider.send_message("1", "x")
    with pytest.raises(RuntimeError):
        await provider.list_guilds()


@pytest.mark.asyncio
async def test_disconnect_clears_stored_credentials():
    vault = InMemorySecretVault()
    provider = _provider_with_token(vault)
    await provider.disconnect()
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_service_send_fails_fast_when_provider_unhealthy():
    service = DiscordService(DisconnectedDiscordProvider())
    with pytest.raises(RuntimeError):
        await service.send("1", "hi")


@pytest.mark.asyncio
async def test_service_send_and_list_guilds_via_mock_provider():
    provider = MockDiscordProvider()
    provider.guilds = [DiscordGuild(id="1", name="Guild One")]
    service = DiscordService(provider)

    receipt = await service.send("111", "reply!")
    assert receipt.verified is True
    assert provider.sent[0] == ("111", "reply!")

    guilds = await service.list_guilds()
    assert guilds == [DiscordGuild(id="1", name="Guild One")]


def test_permission_for_list_guilds_is_l0_and_send_is_l1():
    from app.schemas.approvals import PermissionLevel

    tool = DiscordTool(DiscordService(MockDiscordProvider()))
    assert tool.permission_for({"action": "list_guilds"}) == PermissionLevel.L0
    assert tool.permission_for({"action": "send", "channel_id": "1", "content": "hi"}) == PermissionLevel.L1
    # Unknown/missing action defaults to the higher (send) tier — fail-safe.
    assert tool.permission_for({}) == PermissionLevel.L1


@pytest.mark.asyncio
async def test_tool_send_requires_channel_id_and_content():
    tool = DiscordTool(DiscordService(MockDiscordProvider()))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "send", "content": "hi"}, context=None)
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "send", "channel_id": "1"}, context=None)


@pytest.mark.asyncio
async def test_tool_send_success_returns_receipt_output():
    tool = DiscordTool(DiscordService(MockDiscordProvider()))
    result = await tool.execute({"action": "send", "channel_id": "42", "content": "hello"}, context=None)
    assert result.structured_output["channel_id"] == "42"
    assert result.structured_output["verified"] is True


@pytest.mark.asyncio
async def test_tool_list_guilds_returns_wrapped_output():
    provider = MockDiscordProvider()
    provider.guilds = [DiscordGuild(id="9", name="Server Nine")]
    tool = DiscordTool(DiscordService(provider))
    result = await tool.execute({"action": "list_guilds"}, context=None)
    assert result.structured_output["guilds"][0]["id"] == "9"


@pytest.mark.asyncio
async def test_tool_rejects_unsupported_action():
    tool = DiscordTool(DiscordService(MockDiscordProvider()))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "unknown"}, context=None)


@pytest.mark.asyncio
async def test_tool_health_reflects_provider_health():
    tool = DiscordTool(DiscordService(MockDiscordProvider()))
    health = await tool.health()
    assert health["healthy"] is True


# --- REST API tests (connect/disconnect/status/send), mirroring the
# instagram/telegram router test shape via FastAPI's TestClient against a
# minimal app carrying only the discord router + app.state.

@pytest.mark.asyncio
async def test_api_connect_verifies_token_before_reporting_connected():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.discord import router as discord_router

    def handler(request: httpx.Request) -> httpx.Response:
        if "/users/@me" in str(request.url):
            return httpx.Response(200, json={"id": "1", "username": "vyom_bot"})
        return httpx.Response(404)

    vault = InMemorySecretVault()
    provider = RealDiscordProvider(vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = DiscordService(provider)

    app = FastAPI()
    app.include_router(discord_router)
    app.state.discord_provider = provider
    app.state.discord_service = service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/discord/connect", json={"bot_token": "fake-bot-token"})
        assert response.status_code == 200
        assert response.json()["status"] == "connected"

        status_response = await client.get("/api/discord/status")
        assert status_response.json()["connected"] is True

        disconnect_response = await client.post("/api/discord/disconnect")
        assert disconnect_response.json()["status"] == "disconnected"

        status_after = await client.get("/api/discord/status")
        assert status_after.json()["connected"] is False


@pytest.mark.asyncio
async def test_api_connect_rejects_bad_token_with_401():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.discord import router as discord_router

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized", "code": 0})

    vault = InMemorySecretVault()
    provider = RealDiscordProvider(vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = DiscordService(provider)

    app = FastAPI()
    app.include_router(discord_router)
    app.state.discord_provider = provider
    app.state.discord_service = service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/discord/connect", json={"bot_token": "bad-token"})
        assert response.status_code == 401

        # A rejected connect must not leave stale credentials behind.
        status_response = await client.get("/api/discord/status")
        assert status_response.json()["connected"] is False


@pytest.mark.asyncio
async def test_api_send_returns_503_when_disconnected():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.discord import router as discord_router

    provider = DisconnectedDiscordProvider()
    service = DiscordService(provider)

    app = FastAPI()
    app.include_router(discord_router)
    app.state.discord_provider = provider
    app.state.discord_service = service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/discord/send", json={"channel_id": "1", "content": "hi"})
        assert response.status_code == 503
