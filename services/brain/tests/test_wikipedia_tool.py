"""Unit tests for built-in WikipediaTool."""

from __future__ import annotations

import httpx
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.wikipedia_tool import WikipediaTool


@pytest.mark.asyncio
async def test_wikipedia_tool_metadata():
    tool = WikipediaTool()
    assert tool.metadata.name == "wikipedia"
    assert tool.permission_for({}) == PermissionLevel.L0


@pytest.mark.asyncio
async def test_wikipedia_summary_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "title": "Albert Einstein",
                "extract": "Albert Einstein was a German-born theoretical physicist.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Albert_Einstein"}},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    tool = WikipediaTool(client=client)

    result = await tool.execute({"action": "summary", "query": "Albert Einstein"}, context=None)
    assert result.success is True
    assert "Albert Einstein was a German-born" in result.summary
    assert result.structured_output["query"] == "Albert Einstein"


@pytest.mark.asyncio
async def test_wikipedia_search():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=["python", ["Python", "Python (programming language)", "Monty Python"], [], []],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    tool = WikipediaTool(client=client)

    result = await tool.execute({"action": "search", "query": "python", "limit": 3}, context=None)
    assert result.success is True
    assert "Found 3 Wikipedia results" in result.summary
    assert len(result.structured_output["results"]) == 3


@pytest.mark.asyncio
async def test_wikipedia_missing_query():
    tool = WikipediaTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "summary", "query": ""}, context=None)
