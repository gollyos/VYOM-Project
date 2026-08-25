from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from .schemas import ResearchPlan, Source, SourceType


class SearchProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    async def health(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]: ...


class DisconnectedSearchProvider(SearchProvider):
    """Honest default: no live search provider is configured."""

    name = "disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "No search provider is configured"

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        raise RuntimeError("No search provider is configured")


class LocalFixtureSearchProvider(SearchProvider):
    """Deterministic offline provider for demos/tests. Every record is
    labeled with publisher 'local-fixture' and can never be mistaken for a
    live web result."""

    name = "local_fixture"

    def __init__(self, fixtures: dict[str, list[dict[str, Any]]] | None = None):
        self.fixtures = fixtures or {}

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        key = query.strip().lower()
        for fixture_key, results in self.fixtures.items():
            if fixture_key in key or key in fixture_key:
                return results[:limit]
        return [
            {
                "url": f"https://docs.example.test/{quote(key)[:40]}",
                "title": f"Reference material for {query}",
                "publisher": "local-fixture",
                "source_type": SourceType.DOCUMENTATION.value,
                "excerpt": f"Local fixture placeholder result for '{query}'. No live network call was made.",
            }
        ][:limit]


class BrowserSearchProvider(SearchProvider):
    """Uses the Browser Agent to query a real search engine. Off by default
    (see config/research.yaml); requires real network access and is never
    used inside automated tests."""

    name = "browser_search"

    def __init__(self, browser_actions: Any, url_template: str):
        self.browser_actions = browser_actions
        self.url_template = url_template

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    @staticmethod
    def _resolve_result_url(href: str, search_host: str) -> str | None:
        """The real target of one search-result link, or None if `href`
        is not an actual result (an internal nav link on the search
        engine's own page - about/privacy/settings - or not http(s)).

        DuckDuckGo's HTML results wrap every real result through its own
        redirector (`//duckduckgo.com/l/?uddg=<encoded target>&rut=...`),
        so a same-host href is not automatically noise - it must be
        decoded first, and only treated as noise if decoding finds
        nothing to decode."""
        if not href:
            return None
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https"):
            return None
        if parsed.netloc != search_host:
            return href
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return unquote(target) if target else None

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        url = self.url_template.format(query=quote(query))
        search_host = urlparse(url).netloc
        await self.browser_actions.perform("open", {"url": url})
        # DuckDuckGo's HTML results are protocol-relative (`//duckduckgo.com/
        # l/?uddg=<target>`), NOT absolute-http — a selector of only
        # `a[href^='http']` matched just the handful of absolute external
        # links and silently dropped every real result, so a research task
        # that should have found sources discovered ZERO. Match both forms;
        # the browser resolves each to an absolute href via `.href`, and
        # `_resolve_result_url` decodes the uddg redirect.
        extracted = await self.browser_actions.perform(
            "extract", {"selector": "a[href^='http'], a[href^='//']"})
        texts = extracted.get("items", [])
        hrefs = extracted.get("hrefs", [])
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for text, href in zip(texts, hrefs):
            # BEFORE this fix, every result reused the SEARCH PAGE's own
            # url here - so SourceDiscovery's dedup-by-url silently
            # collapsed an entire search down to at most one usable
            # source, and the one source it kept pointed at the results
            # page itself, not any real result. Each result now carries
            # its OWN resolved target url.
            resolved = self._resolve_result_url(href or "", search_host)
            label = (text or "").strip()
            if not resolved or not label or resolved in seen:
                continue
            seen.add(resolved)
            results.append({
                "url": resolved,
                "title": label[:200],
                "publisher": "web-search",
                "source_type": SourceType.UNKNOWN.value,
                "excerpt": label[:300],
            })
            if len(results) >= limit:
                break
        return results


class SerpApiSearchProvider(SearchProvider):
    """Real Google search results via SerpAPI (https://serpapi.com) — a
    paid, structured JSON search API, chosen over scraping DuckDuckGo's
    HTML (BrowserSearchProvider above) when a client provides their own
    key: it's faster, more reliable (no page-structure scraping to
    break), and returns real Google results rather than DuckDuckGo's.
    Connected via a simple API-key paste (POST /api/search/serpapi/
    connect), matching the App-Password/access-token connect pattern
    used by Gmail/Instagram/Meta-Ads elsewhere in this repo rather than
    a full OAuth flow — SerpAPI itself only ever authenticates by key."""

    name = "serpapi"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def health(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "SerpAPI is not connected (no key configured)"
        try:
            response = await self._pooled().get(
                "https://serpapi.com/search",
                params={"engine": "google", "q": "test", "api_key": self.api_key, "num": 1},
            )
        except Exception as error:
            return False, f"SerpAPI health check failed: {error}"[:300]
        if response.status_code == 401:
            return False, "SerpAPI rejected the key (401 Unauthorized)"
        if response.status_code >= 400:
            return False, f"SerpAPI returned HTTP {response.status_code}"
        data = response.json()
        if "error" in data:
            return False, f"SerpAPI error: {data['error']}"[:300]
        return True, None

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        response = await self._pooled().get(
            "https://serpapi.com/search",
            params={"engine": "google", "q": query, "api_key": self.api_key, "num": limit},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"SerpAPI search failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"SerpAPI error: {data['error']}")
        results: list[dict[str, Any]] = []
        for item in data.get("organic_results", [])[:limit]:
            url = item.get("link", "")
            if not url:
                continue
            results.append({
                "url": url,
                "title": item.get("title") or url,
                "publisher": "serpapi-google",
                "source_type": SourceType.UNKNOWN.value,
                "excerpt": item.get("snippet", ""),
            })
        return results


class SourceDiscovery:
    """Fans a bounded set of queries out across configured providers,
    de-duplicates by URL, and never exceeds the plan's source budget."""

    def __init__(self, providers: list[SearchProvider] | None = None):
        self.providers = providers or [DisconnectedSearchProvider()]

    async def discover(self, plan: ResearchPlan, queries: list[str]) -> list[Source]:
        sources: list[Source] = []
        seen_urls: set[str] = set()
        per_query_limit = max(1, plan.budget.max_sources // max(1, len(queries) or 1))
        for query in queries:
            for provider in self.providers:
                healthy, _ = await provider.health()
                if not healthy:
                    continue
                try:
                    results = await provider.search(query, limit=per_query_limit)
                except Exception:
                    continue
                for item in results:
                    url = str(item.get("url", "")).strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    raw_type = item.get("source_type", SourceType.UNKNOWN.value)
                    try:
                        source_type = SourceType(raw_type)
                    except ValueError:
                        source_type = SourceType.UNKNOWN
                    sources.append(
                        Source(
                            url=url,
                            title=str(item.get("title") or url),
                            publisher=str(item.get("publisher") or "unknown"),
                            source_type=source_type,
                            excerpt=str(item.get("excerpt") or ""),
                        )
                    )
                break
            if len(sources) >= plan.budget.max_sources:
                break
        return sources[: plan.budget.max_sources]
