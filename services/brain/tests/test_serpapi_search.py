"""Tests for SerpApiSearchProvider added this session: real SerpAPI
(https://serpapi.com) Google search results, connected via a simple
API-key paste (POST /api/search/serpapi/connect) rather than OAuth,
matching the App-Password/access-token self-service connect pattern
used elsewhere in this repo. Uses httpx.MockTransport against a
realistically-shaped SerpAPI response.
"""
from __future__ import annotations

import httpx
import pytest

from app.research.source_discovery import SerpApiSearchProvider


def _provider_with_transport(handler) -> SerpApiSearchProvider:
    provider = SerpApiSearchProvider("fake-serpapi-key")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_health_false_when_no_key():
    provider = SerpApiSearchProvider("")
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_on_real_looking_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "fake-serpapi-key"
        assert request.url.params["engine"] == "google"
        return httpx.Response(200, json={"organic_results": [{"title": "x", "link": "https://example.com"}]})

    provider = _provider_with_transport(handler)
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_health_false_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    provider = _provider_with_transport(handler)
    healthy, error = await provider.health()
    assert healthy is False
    assert "rejected" in error.lower()


@pytest.mark.asyncio
async def test_health_false_on_serpapi_error_field():
    """SerpAPI returns HTTP 200 with an 'error' field for some failure
    modes (e.g. rate limit) — must not be mistaken for success."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Your account has run out of searches"})

    provider = _provider_with_transport(handler)
    healthy, error = await provider.health()
    assert healthy is False
    assert "run out of searches" in error


@pytest.mark.asyncio
async def test_search_parses_real_organic_results_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "organic_results": [
                {"title": "Result One", "link": "https://a.example.com", "snippet": "First snippet"},
                {"title": "Result Two", "link": "https://b.example.com", "snippet": "Second snippet"},
            ],
        })

    provider = _provider_with_transport(handler)
    results = await provider.search("test query", limit=5)
    assert len(results) == 2
    assert results[0]["url"] == "https://a.example.com"
    assert results[0]["title"] == "Result One"
    assert results[0]["publisher"] == "serpapi-google"
    assert results[0]["excerpt"] == "First snippet"


@pytest.mark.asyncio
async def test_search_respects_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "organic_results": [{"title": f"R{i}", "link": f"https://x{i}.example.com"} for i in range(10)],
        })

    provider = _provider_with_transport(handler)
    results = await provider.search("test", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_raises_on_real_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Missing query parameter"})

    provider = _provider_with_transport(handler)
    with pytest.raises(RuntimeError, match="Missing query parameter"):
        await provider.search("test")


@pytest.mark.asyncio
async def test_search_skips_results_with_no_link():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "organic_results": [{"title": "No link here"}, {"title": "Has link", "link": "https://c.example.com"}],
        })

    provider = _provider_with_transport(handler)
    results = await provider.search("test")
    assert len(results) == 1
    assert results[0]["url"] == "https://c.example.com"
