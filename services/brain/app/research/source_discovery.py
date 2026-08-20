from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

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

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        url = self.url_template.format(query=quote(query))
        await self.browser_actions.perform("open", {"url": url})
        extracted = await self.browser_actions.perform("extract", {"selector": "a[href^='http']"})
        items = [str(item) for item in extracted.get("items", [])][:limit]
        return [
            {
                "url": url,
                "title": text or query,
                "publisher": "web-search",
                "source_type": SourceType.UNKNOWN.value,
                "excerpt": text,
            }
            for text in items
        ]


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
