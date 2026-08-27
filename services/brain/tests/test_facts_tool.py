"""Tests for the free, keyless TriviaFactsTool: advice / fact / joke,
permission tiering, and validation errors. Uses httpx.MockTransport against
realistically-shaped Advice Slip / Useless Facts / Official Joke API
responses — never a real network call.
"""
from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.facts_tool import TriviaFactsTool


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_advice_returns_slip_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "adviceslip" in str(request.url)
        return httpx.Response(200, json={"slip": {"id": 1, "advice": "Always double-check your parachute."}})

    tool = TriviaFactsTool(_client_for(handler))
    result = await tool.execute({"action": "advice"}, context=None)

    assert result.success is True
    assert result.structured_output["advice"] == "Always double-check your parachute."
    assert result.summary == "Always double-check your parachute."


@pytest.mark.asyncio
async def test_fact_returns_text_and_source():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "uselessfacts" in str(request.url)
        return httpx.Response(200, json={"text": "Bananas are berries.", "source_url": "https://example.com"})

    tool = TriviaFactsTool(_client_for(handler))
    result = await tool.execute({"action": "fact"}, context=None)

    assert result.structured_output["fact"] == "Bananas are berries."
    assert result.structured_output["source"] == "https://example.com"


@pytest.mark.asyncio
async def test_joke_returns_setup_and_punchline():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "joke-api" in str(request.url)
        return httpx.Response(200, json={"type": "general", "setup": "Why did the dev go broke?", "punchline": "Because he used up all his cache."})

    tool = TriviaFactsTool(_client_for(handler))
    result = await tool.execute({"action": "joke"}, context=None)

    assert result.structured_output["setup"] == "Why did the dev go broke?"
    assert result.structured_output["punchline"] == "Because he used up all his cache."
    assert "Why did the dev go broke?" in result.summary


@pytest.mark.asyncio
async def test_empty_advice_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"slip": {}})

    tool = TriviaFactsTool(_client_for(handler))
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "advice"}, context=None)


@pytest.mark.asyncio
async def test_network_failure_raises_clear_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tool = TriviaFactsTool(_client_for(handler))
    with pytest.raises(ToolValidationError, match="Lookup failed"):
        await tool.execute({"action": "joke"}, context=None)


@pytest.mark.asyncio
async def test_unsupported_action_raises_validation_error():
    tool = TriviaFactsTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "bogus"}, context=None)


def test_permission_for_is_always_l0():
    tool = TriviaFactsTool()
    assert tool.permission_for({"action": "advice"}) == PermissionLevel.L0
    assert tool.permission_for({}) == PermissionLevel.L0
