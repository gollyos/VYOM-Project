"""Regression tests for the search-provider FALLBACK ordering fixed this
session. The user's concern: VYOM was burning paid SerpAPI quota (and
calling it FIRST) on every research query, and a second real bug meant
a provider returning ZERO results never fell through to the next one.

Two real bugs found and fixed together:
  (A) DeepResearchTask.from_config() listed SerpApiSearchProvider FIRST
      (paid) ahead of the free BrowserSearchProvider — so every task hit
      the paid API before the free one at all.
  (B) SourceDiscovery.discover() unconditionally `break`-ed out of the
      provider loop after the FIRST healthy provider even when it
      returned zero results — so even after reordering, a browser search
      that parsed to nothing (DuckDuckGo markup changed, network hiccup)
      would never fall through to SerpAPI/the next provider.

These tests lock in that the free path is tried first by default, that
SerpAPI is only reached as a fallback, and that zero results falls
through instead of stopping the chain.
"""
from __future__ import annotations

from app.research.orchestrator import DeepResearchTask
from app.research.schemas import ResearchBudget, ResearchDepth, ResearchPlan
from app.research.source_discovery import BrowserSearchProvider, LocalFixtureSearchProvider, SerpApiSearchProvider, SourceDiscovery


class _FakeBrowserActions:
    """Returns NO results (an empty result list) — the 'browser returned
    nothing' scenario the second bug is about."""

    async def perform(self, action: str, params: dict | None = None):
        if action == "open":
            return {}
        if action == "extract":
            return {"items": [], "hrefs": []}
        return {}


def test_free_browser_wins_over_serpapi_by_default():
    """(A) With default config (priority: fallback), the FREE browser
    provider must be listed BEFORE the paid SerpAPI provider — so a
    research query tries the free path first and only touches SerpAPI
    if the free path comes up empty."""
    config = {
        "search_providers": {
            "browser_search": {"enabled": True, "search_url_template": "https://duckduckgo.com/html/?q={query}"},
            "local_fixture": {"enabled": False},
            "serpapi": {"enabled": True, "priority": "fallback"},
        }
    }
    task = DeepResearchTask.from_config(config, browser_actions=_FakeBrowserActions(), serpapi_key="fake-key")
    provider_classes = [type(p) for p in task.source_discovery.providers]
    browser_index = provider_classes.index(BrowserSearchProvider)
    serpapi_index = provider_classes.index(SerpApiSearchProvider)
    assert browser_index < serpapi_index, "free browser search should be tried before paid SerpAPI by default"


def test_explicit_primary_priority_puts_serpapi_first():
    """(A) The opt-in 'priority: primary' must genuinely move SerpAPI
    ahead of browser_search — this is the escape hatch for a client who
    always wants structured Google JSON."""
    config = {
        "search_providers": {
            "browser_search": {"enabled": True, "search_url_template": "https://duckduckgo.com/html/?q={query}"},
            "local_fixture": {"enabled": False},
            "serpapi": {"enabled": True, "priority": "primary"},
        }
    }
    task = DeepResearchTask.from_config(config, browser_actions=_FakeBrowserActions(), serpapi_key="fake-key")
    provider_classes = [type(p) for p in task.source_discovery.providers]
    assert provider_classes[0] is SerpApiSearchProvider, "primary priority should put Serpapi first"


def test_zero_results_falls_through_to_next_provider():
    """(B) The real bug: if the first provider returns ZERO results, the
    loop must continue to the NEXT provider instead of stopping. Here
    the browser provider returns empty -> SerpAPI is tried next -> its
    result is surfaced."""
    browser = BrowserSearchProvider(_FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")

    class _FakeSerp:
        name = "serpapi"

        async def health(self):
            return True, None

        async def search(self, query, *, limit=5):
            return [{"url": f"https://serp-result.example/{query}", "title": "SerpAPI result", "publisher": "serpapi-google"}]

    discovery = SourceDiscovery([browser, _FakeSerp()])
    plan = ResearchPlan(
        goal="test", depth=ResearchDepth.STANDARD,
        budget=ResearchBudget(max_queries=1, max_sources=4, max_model_calls=2, max_runtime_seconds=60, max_cost=0.10),
    )
    sources = []
    import asyncio

    async def run():
        return await discovery.discover(plan, ["hello world"])

    sources = asyncio.run(run())
    assert len(sources) == 1, "zero-result browser search should fall through to the next provider"
    assert sources[0].publisher == "serpapi-google"


def test_provider_exception_does_not_block_fallback():
    """A provider that RAISES (network error, API down) must also be
    skipped so the fallback chain continues — never silently end the
    discovery because one provider crashed."""
    class _Raising:
        name = "raising"

        async def health(self):
            return True, None

        async def search(self, query, *, limit=5):
            raise RuntimeError("provider down")

    class _FakeSerp:
        name = "serpapi"

        async def health(self):
            return True, None

        async def search(self, query, *, limit=5):
            return [{"url": "https://ok.example", "title": "Ok", "publisher": "ok"}]

    discovery = SourceDiscovery([_Raising(), _FakeSerp()])
    plan = ResearchPlan(
        goal="test", depth=ResearchDepth.STANDARD,
        budget=ResearchBudget(max_queries=1, max_sources=4, max_model_calls=2, max_runtime_seconds=60, max_cost=0.10),
    )
    import asyncio

    sources = asyncio.run(discovery.discover(plan, ["x"]))
    assert len(sources) == 1
    assert sources[0].publisher == "ok"


def test_serpapi_not_called_when_browser_succeeds():
    """The actual quota-saving behavior: when the free browser provider
    returns real results, SerpAPI (paid) must NOT be called at all."""
    call_log = {"serpapi_called": False}

    class _WorkingBrowser:
        name = "browser"

        async def health(self):
            return True, None

        async def search(self, query, *, limit=5):
            return [{"url": "https://free.example", "title": "Free result", "publisher": "web-search"}]

    class _SpySerp:
        name = "serpapi"

        async def health(self):
            return True, None

        async def search(self, query, *, limit=5):
            call_log["serpapi_called"] = True
            return [{"url": "https://paid.example", "title": "Paid", "publisher": "serpapi-google"}]

    discovery = SourceDiscovery([_WorkingBrowser(), _SpySerp()])
    plan = ResearchPlan(
        goal="test", depth=ResearchDepth.STANDARD,
        budget=ResearchBudget(max_queries=1, max_sources=4, max_model_calls=2, max_runtime_seconds=60, max_cost=0.10),
    )
    import asyncio

    sources = asyncio.run(discovery.discover(plan, ["x"]))
    assert len(sources) == 1
    assert sources[0].publisher == "web-search"
    assert call_log["serpapi_called"] is False, "SerpAPI (paid) must not be called when the free provider succeeds"
