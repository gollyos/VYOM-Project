"""Tests for the free, keyless Frankfurter (ECB) CurrencyTool: convert +
latest rates, permission tiering, and validation errors. Uses
httpx.MockTransport against realistically-shaped Frankfurter responses —
never a real network call.
"""
from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.currency_tool import CurrencyTool


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_convert_returns_converted_amount_and_rate():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "frankfurter" in str(request.url)
        assert "base=USD" in str(request.url)
        assert "symbols=INR" in str(request.url)
        return httpx.Response(200, json={"amount": 100.0, "base": "USD", "date": "2026-08-27", "rates": {"INR": 8350.0}})

    tool = CurrencyTool(_client_for(handler))
    result = await tool.execute({"action": "convert", "from_currency": "usd", "to_currency": "inr", "amount": 100}, context=None)

    assert result.success is True
    assert result.structured_output["converted_amount"] == 8350.0
    assert result.structured_output["from_currency"] == "USD"
    assert result.structured_output["to_currency"] == "INR"
    assert "USD" in result.summary and "INR" in result.summary


@pytest.mark.asyncio
async def test_convert_defaults_amount_to_one():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"amount": 1.0, "base": "EUR", "date": "2026-08-27", "rates": {"GBP": 0.86}})

    tool = CurrencyTool(_client_for(handler))
    result = await tool.execute({"action": "convert", "from_currency": "EUR", "to_currency": "GBP"}, context=None)
    assert result.structured_output["amount"] == 1.0
    assert result.structured_output["rate"] == pytest.approx(0.86)


@pytest.mark.asyncio
async def test_rates_returns_latest_rates_for_base():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"amount": 1.0, "base": "USD", "date": "2026-08-27", "rates": {"INR": 83.5, "EUR": 0.92}})

    tool = CurrencyTool(_client_for(handler))
    result = await tool.execute({"action": "rates", "base_currency": "usd"}, context=None)

    assert result.structured_output["base_currency"] == "USD"
    assert result.structured_output["rates"]["INR"] == 83.5


@pytest.mark.asyncio
async def test_missing_currencies_raises_validation_error():
    tool = CurrencyTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "convert", "from_currency": "USD"}, context=None)


@pytest.mark.asyncio
async def test_non_numeric_amount_raises_validation_error():
    tool = CurrencyTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "convert", "from_currency": "USD", "to_currency": "INR", "amount": "not-a-number"}, context=None)


@pytest.mark.asyncio
async def test_unsupported_target_currency_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"amount": 1.0, "base": "USD", "date": "2026-08-27", "rates": {}})

    tool = CurrencyTool(_client_for(handler))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "convert", "from_currency": "USD", "to_currency": "ZZZ"}, context=None)


@pytest.mark.asyncio
async def test_network_failure_raises_clear_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tool = CurrencyTool(_client_for(handler))
    with pytest.raises(ToolValidationError, match="Currency lookup failed"):
        await tool.execute({"action": "convert", "from_currency": "USD", "to_currency": "INR"}, context=None)


@pytest.mark.asyncio
async def test_unsupported_action_raises_validation_error():
    tool = CurrencyTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "bogus"}, context=None)


def test_permission_for_is_always_l0():
    tool = CurrencyTool()
    assert tool.permission_for({"action": "convert"}) == PermissionLevel.L0
    assert tool.permission_for({}) == PermissionLevel.L0
