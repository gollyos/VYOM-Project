from __future__ import annotations

from app.research.schemas import ResearchBudget, ResearchDepth, ResearchPlan
from app.research.source_discovery import BrowserSearchProvider, SourceDiscovery


class FakeBrowserActions:
    """Returns realistic DuckDuckGo HTML result shapes: real results
    wrapped through DDG's own /l/?uddg= redirector, internal nav links
    that are noise, and a duplicate target reached via two different
    tracking params - exactly what a real search results page contains."""

    def __init__(self, extracted: dict | None = None):
        self.extracted = extracted or {
            "items": [
                "Python Official Site", "About", "Privacy",
                "Python Official Site (mirror)", "Real Python Tutorials", "",
            ],
            "hrefs": [
                "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&rut=abc",
                "https://duckduckgo.com/about",
                "https://duckduckgo.com/privacy",
                "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F&rut=xyz",
                "https://duckduckgo.com/l/?uddg=https%3A%2F%2Frealpython.com%2F&rut=def",
                "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fnoise.example%2F&rut=ghi",
            ],
        }
        self.opened_urls: list[str] = []

    async def perform(self, action, inputs):
        if action == "open":
            self.opened_urls.append(inputs["url"])
            return {"url": inputs["url"], "title": "DuckDuckGo"}
        if action == "extract":
            return {**self.extracted, "url": self.opened_urls[-1] if self.opened_urls else ""}
        raise ValueError(f"unexpected action: {action}")


def _plan(max_sources: int = 10) -> ResearchPlan:
    return ResearchPlan(
        goal="python programming language",
        depth=ResearchDepth.STANDARD,
        budget=ResearchBudget(max_sources=max_sources, max_queries=1, max_model_calls=1,
                               max_browser_time_seconds=60, max_cost=0.1, max_runtime_seconds=60),
    )


# ======================================================================
# BrowserSearchProvider._resolve_result_url
# ======================================================================

def test_resolve_decodes_the_duckduckgo_redirect_wrapper():
    resolved = BrowserSearchProvider._resolve_result_url(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2Fdocs&rut=abc",
        "duckduckgo.com",
    )
    assert resolved == "https://python.org/docs"


def test_resolve_passes_through_a_plain_non_search_host_href():
    resolved = BrowserSearchProvider._resolve_result_url("https://example.com/page", "duckduckgo.com")
    assert resolved == "https://example.com/page"


def test_resolve_rejects_internal_nav_links_with_no_redirect_target():
    assert BrowserSearchProvider._resolve_result_url("https://duckduckgo.com/about", "duckduckgo.com") is None
    assert BrowserSearchProvider._resolve_result_url("https://duckduckgo.com/privacy", "duckduckgo.com") is None


def test_resolve_rejects_non_http_and_empty_hrefs():
    assert BrowserSearchProvider._resolve_result_url("", "duckduckgo.com") is None
    assert BrowserSearchProvider._resolve_result_url("javascript:void(0)", "duckduckgo.com") is None
    assert BrowserSearchProvider._resolve_result_url("mailto:x@example.com", "duckduckgo.com") is None


# ======================================================================
# BrowserSearchProvider.search
# ======================================================================

async def test_search_returns_distinct_real_target_urls_not_the_search_page():
    """Before the fix, every result reused the SEARCH PAGE's own url, so
    every result after the first looked like a duplicate and was thrown
    away. Real per-result urls must survive here."""
    provider = BrowserSearchProvider(FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    results = await provider.search("python", limit=5)
    urls = [r["url"] for r in results]
    assert urls == ["https://python.org/", "https://realpython.com/"]
    assert all(url != "https://duckduckgo.com/html/?q=python" for url in urls)


async def test_search_deduplicates_the_same_target_reached_via_different_tracking_params():
    provider = BrowserSearchProvider(FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    results = await provider.search("python", limit=5)
    assert len(results) == 2  # python.org appears twice in the fixture, realpython.com once


async def test_search_skips_internal_nav_links_and_empty_labels():
    provider = BrowserSearchProvider(FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    results = await provider.search("python", limit=5)
    titles = [r["title"] for r in results]
    assert "About" not in titles
    assert "Privacy" not in titles
    assert "" not in titles


async def test_search_respects_the_limit():
    provider = BrowserSearchProvider(FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    results = await provider.search("python", limit=1)
    assert len(results) == 1


# ======================================================================
# End-to-end through SourceDiscovery: the real regression this fixes
# ======================================================================

async def test_source_discovery_now_yields_more_than_one_real_source():
    """This is the actual bug as it manifested one layer up: with the
    old same-url-for-every-result behaviour, SourceDiscovery's own
    dedup-by-url collapsed an entire successful search down to at most
    one usable Source, no matter how many real results the search
    engine returned."""
    provider = BrowserSearchProvider(FakeBrowserActions(), "https://duckduckgo.com/html/?q={query}")
    discovery = SourceDiscovery([provider])
    sources = await discovery.discover(_plan(), ["python programming"])
    assert len(sources) == 2
    assert {s.url for s in sources} == {"https://python.org/", "https://realpython.com/"}
