"""Tests for the free, keyless CoinGecko CryptoTool: price + trending,
permission tiering, rate-limit handling, and validation errors. Uses
httpx.MockTransport against realistically-shaped CoinGecko responses —
never a real network call.
"""
from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.crypto_tool import CryptoTool


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_price_returns_prices_for_multiple_coins_and_currencies():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "simple/price" in str(request.url)
        assert "ids=bitcoin%2Cethereum" in str(request.url) or "ids=bitcoin,ethereum" in str(request.url)
        return httpx.Response(200, json={
            "bitcoin": {"usd": 65000.0, "usd_24h_change": 2.3, "inr": 5400000.0, "inr_24h_change": 2.1},
            "ethereum": {"usd": 3400.0, "usd_24h_change": -1.1, "inr": 283000.0, "inr_24h_change": -1.3},
        })

    tool = CryptoTool(_client_for(handler))
    result = await tool.execute({"action": "price", "coin_ids": "bitcoin,ethereum", "vs_currencies": "usd,inr"}, context=None)

    assert result.success is True
    assert result.structured_output["prices"]["bitcoin"]["usd"] == 65000.0
    assert "bitcoin" in result.summary and "ethereum" in result.summary


@pytest.mark.asyncio
async def test_price_defaults_to_bitcoin_usd():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "ids=bitcoin" in str(request.url)
        return httpx.Response(200, json={"bitcoin": {"usd": 65000.0}})

    tool = CryptoTool(_client_for(handler))
    result = await tool.execute({"action": "price"}, context=None)
    assert result.structured_output["prices"]["bitcoin"]["usd"] == 65000.0


@pytest.mark.asyncio
async def test_price_accepts_list_inputs():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bitcoin": {"usd": 65000.0}})

    tool = CryptoTool(_client_for(handler))
    result = await tool.execute({"action": "price", "coin_ids": ["bitcoin"], "vs_currencies": ["usd"]}, context=None)
    assert result.success is True


@pytest.mark.asyncio
async def test_trending_returns_coin_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "search/trending" in str(request.url)
        return httpx.Response(200, json={
            "coins": [
                {"item": {"id": "dogecoin", "name": "Dogecoin", "symbol": "DOGE", "market_cap_rank": 10}},
                {"item": {"id": "pepe", "name": "Pepe", "symbol": "PEPE", "market_cap_rank": 30}},
            ]
        })

    tool = CryptoTool(_client_for(handler))
    result = await tool.execute({"action": "trending"}, context=None)

    assert len(result.structured_output["trending"]) == 2
    assert result.structured_output["trending"][0]["id"] == "dogecoin"
    assert "Dogecoin" in result.summary


@pytest.mark.asyncio
async def test_empty_price_response_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    tool = CryptoTool(_client_for(handler))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "price", "coin_ids": "not-a-real-coin"}, context=None)


@pytest.mark.asyncio
async def test_rate_limit_raises_clear_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    tool = CryptoTool(_client_for(handler))
    with pytest.raises(ToolValidationError, match="rate limit"):
        await tool.execute({"action": "price"}, context=None)


@pytest.mark.asyncio
async def test_network_failure_raises_clear_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tool = CryptoTool(_client_for(handler))
    with pytest.raises(ToolValidationError, match="Crypto lookup failed"):
        await tool.execute({"action": "price"}, context=None)


@pytest.mark.asyncio
async def test_unsupported_action_raises_validation_error():
    tool = CryptoTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "bogus"}, context=None)


def test_permission_for_is_always_l0():
    tool = CryptoTool()
    assert tool.permission_for({"action": "price"}) == PermissionLevel.L0
    assert tool.permission_for({}) == PermissionLevel.L0
