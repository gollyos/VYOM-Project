"""Unit tests for built-in NewsTool."""

from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools_builtin.news_tool import NewsTool


SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>AI Breakthrough Announced Today</title>
      <link>https://news.example.com/ai-breakthrough</link>
      <pubDate>Thu, 27 Aug 2026 09:00:00 GMT</pubDate>
      <source>TechDaily</source>
    </item>
    <item>
      <title>Global Markets Rally on Positive Earnings</title>
      <link>https://news.example.com/markets-rally</link>
      <pubDate>Thu, 27 Aug 2026 08:30:00 GMT</pubDate>
      <source>MarketWatch</source>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_news_tool_metadata():
    tool = NewsTool()
    assert tool.metadata.name == "news"
    assert tool.permission_for({}) == PermissionLevel.L0


@pytest.mark.asyncio
async def test_news_tool_rss_fallback():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_RSS_XML.encode("utf-8"))

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    tool = NewsTool(client=client)

    result = await tool.execute({"action": "top_headlines", "limit": 2}, context=None)
    assert result.success is True
    assert "AI Breakthrough Announced Today" in result.summary
    assert len(result.structured_output["articles"]) == 2
