"""Tests for the keyless OpenCode-Zen free-tier provider.

This provider exists so VYOM keeps a working LLM even with every paid
API key empty: the OpenCode Zen relay (https://opencode.ai/zen/v1)
serves a curated "-free" model family anonymously. Same mechanism used
to connect Hermes Agent to "Ox Alpha" for free (see
hermes_cli/models.py: opencode_zen_free_headers /
OPENCODE_ZEN_FREE_KEYLESS_PLACEHOLDER).
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import ProviderRateLimitError, ProviderRequest, ProviderUnavailableError
from app.providers.opencode_free import OpenCodeFreeProvider
from app.schemas.tasks import TaskProfile


def _request(model: str = "hy3-free") -> ProviderRequest:
    return ProviderRequest(
        model=model, user_request="hello", system_instruction="be brief",
        profile=TaskProfile(),
    )


def _patch_async_client(monkeypatch, handler) -> None:
    """Replace httpx.AsyncClient with one bound to a MockTransport, using
    the ORIGINAL class (monkeypatching httpx.AsyncClient and then calling
    httpx.AsyncClient(...) from inside the replacement recurses forever)."""
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: real_async_client(transport=httpx.MockTransport(handler)),
    )


def test_always_configured_with_zero_keys():
    """The whole point: no credential can ever be missing."""
    provider = OpenCodeFreeProvider(timeout_seconds=10)
    assert provider.configured is True
    assert provider.api_key == "opencode-zen-free-keyless"


@pytest.mark.asyncio
async def test_generate_sends_empty_authorization_header(monkeypatch):
    """The anonymous free route requires an explicit empty Authorization
    header - a MISSING header or any non-empty bearer is rejected by the
    relay (verified live against the real endpoint 2026-08-25)."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hi there"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        })

    _patch_async_client(monkeypatch, handler)
    provider = OpenCodeFreeProvider(timeout_seconds=10)
    result = await provider.generate(_request())

    assert result.text == "hi there"
    assert captured["headers"]["authorization"] == ""
    assert captured["body"]["model"] == "hy3-free"


@pytest.mark.asyncio
async def test_non_free_model_falls_back_to_default_free_model(monkeypatch):
    """A caller passing a paid model slug must not leak it to this
    provider's anonymous route - it always uses a verified free model."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    _patch_async_client(monkeypatch, handler)
    provider = OpenCodeFreeProvider(timeout_seconds=10)
    await provider.generate(_request(model="claude-sonnet-5"))

    assert captured["body"]["model"] == OpenCodeFreeProvider.DEFAULT_MODEL


@pytest.mark.asyncio
async def test_rate_limit_raises_provider_rate_limit_error(monkeypatch):
    _patch_async_client(monkeypatch, lambda r: httpx.Response(429))
    provider = OpenCodeFreeProvider(timeout_seconds=10)
    with pytest.raises(ProviderRateLimitError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_server_error_raises_provider_unavailable(monkeypatch):
    """Regression guard: an upstream outage (observed for x-preview-f-free
    on 2026-08-25 - 'Endpoint is unavailable') must degrade to the normal
    fallback path, not crash the router."""
    _patch_async_client(
        monkeypatch,
        lambda r: httpx.Response(500, json={"error": {"message": "Endpoint is unavailable"}}),
    )
    provider = OpenCodeFreeProvider(timeout_seconds=10)
    with pytest.raises(ProviderUnavailableError):
        await provider.generate(_request())


def test_registered_in_production_provider_registry():
    from app.core.config import Settings
    from app.providers import create_provider_registry

    registry = create_provider_registry(Settings())
    assert "opencode-free" in registry.providers
    assert registry.providers["opencode-free"].configured is True


@pytest.mark.asyncio
async def test_live_call_against_the_real_opencode_zen_relay():
    """Real network call, no mocks - this is the actual contract: a
    genuinely free model answers with zero credentials configured
    anywhere. Skipped automatically if the network is unreachable so it
    never blocks an offline CI run."""
    provider = OpenCodeFreeProvider(timeout_seconds=20)
    try:
        result = await provider.generate(ProviderRequest(
            model="hy3-free", user_request="Reply with exactly: VYOM_LIVE_OK",
            system_instruction="Follow the instruction exactly.",
            profile=TaskProfile(),
        ))
    except ProviderUnavailableError as error:
        pytest.skip(f"opencode.ai free relay unreachable/unavailable: {error}")
    assert result.text
