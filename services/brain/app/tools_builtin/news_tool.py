"""Built-in News Tool for VYOM.

Provides live top headlines and news topic search using NewsAPI (when key is available)
or keyless Google News RSS XML digest.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

logger = logging.getLogger(__name__)


class NewsTool(BaseTool):
    """Free, keyless live news feed & top headlines tool.
    Read-only informational queries, so every action is L0."""

    metadata = ToolMetadata(
        name="news",
        description=(
            "Fetch latest top news headlines or search news by topic/keyword. "
            "Actions: top_headlines, search. Keyless, read-only L0."
        ),
        category="research",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "top_headlines")).strip().lower()
        topic = str(inputs.get("topic", "") or inputs.get("query", "")).strip()
        country = str(inputs.get("country", "in")).strip().lower()
        limit = int(inputs.get("limit", 5))

        client = self._client or httpx.AsyncClient(timeout=8.0)
        close_client = self._client is None

        try:
            api_key = os.getenv("NEWS_API_KEY", "").strip()

            # 1. Try NewsAPI if key is available
            if api_key:
                try:
                    if action == "top_headlines":
                        url = f"https://newsapi.org/v2/top-headlines?country={country}&apiKey={api_key}"
                        if topic:
                            url += f"&q={urllib.parse.quote(topic)}"
                    else:
                        url = f"https://newsapi.org/v2/everything?q={urllib.parse.quote(topic or 'technology')}&sortBy=publishedAt&apiKey={api_key}"

                    resp = await client.get(url)
                    if resp.status_code == 200:
                        articles = resp.json().get("articles", [])[:limit]
                        rows = [
                            {
                                "title": a.get("title", ""),
                                "source": a.get("source", {}).get("name", "News"),
                                "url": a.get("url", ""),
                                "published_at": a.get("publishedAt", ""),
                            }
                            for a in articles
                        ]
                        output = {"action": action, "topic": topic, "articles": rows, "count": len(rows)}
                        evidence = EvidenceItem(
                            type="tool_result",
                            summary=f"Top {len(rows)} news headlines",
                            data=output,
                        )
                        summary_lines = [f"{i+1}. {r['title']} ({r['source']})" for i, r in enumerate(rows)]
                        return ToolResult.completed(
                            "Top news headlines:\n" + "\n".join(summary_lines),
                            output=output,
                            evidence=[evidence],
                        )
                except Exception as exc:
                    logger.warning("NewsAPI call failed, falling back to Google News RSS: %s", exc)

            # 2. Keyless Google News RSS fallback
            if topic:
                rss_query = urllib.parse.quote(topic)
                rss_url = f"https://news.google.com/rss/search?q={rss_query}&hl=en-IN&gl=IN&ceid=IN:en"
            else:
                rss_url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"

            resp = await client.get(rss_url)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                items = root.findall("./channel/item")[:limit]
                rows = []
                for item in items:
                    title = item.findtext("title", "").strip()
                    link = item.findtext("link", "").strip()
                    pub_date = item.findtext("pubDate", "").strip()
                    source = item.findtext("source", "Google News").strip()
                    if title:
                        rows.append({
                            "title": title,
                            "source": source,
                            "url": link,
                            "published_at": pub_date,
                        })

                if rows:
                    output = {"action": action, "topic": topic, "articles": rows, "count": len(rows)}
                    evidence = EvidenceItem(
                        type="tool_result",
                        summary=f"Top {len(rows)} news articles",
                        data=output,
                    )
                    summary_lines = [f"{i+1}. {r['title']}" for i, r in enumerate(rows)]
                    return ToolResult.completed(
                        "Latest news headlines:\n" + "\n".join(summary_lines),
                        output=output,
                        evidence=[evidence],
                    )

            return ToolResult.failed("Unable to retrieve news headlines at the moment.")
        finally:
            if close_client:
                await client.aclose()

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "News RSS / API feed ready"}
