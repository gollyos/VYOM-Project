"""Built-in Wikipedia Knowledge Tool for VYOM.

Provides free, credential-less factual summaries, search, and page content
from Wikipedia using Wikipedia REST API and Action API with async httpx.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult, ToolStatus

logger = logging.getLogger(__name__)

USER_AGENT = "VYOM-Personal-Assistant/0.1.0 (https://vyom.ai; contact@vyom.ai)"


class WikipediaTool(BaseTool):
    """Free, no-API-key Wikipedia lookup tool.
    Read-only informational queries, so every action is L0."""

    metadata = ToolMetadata(
        name="wikipedia",
        description=(
            "Look up concise summaries, search topics, or fetch article information from Wikipedia. "
            "Actions: summary, search, page. Keyless, read-only L0."
        ),
        category="research",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def execute(self, inputs: dict[str, Any], context: ToolContext | None = None) -> ToolResult:
        action = str(inputs.get("action", "summary")).strip().lower()
        query = str(inputs.get("query", "") or inputs.get("topic", "")).strip()

        if not query:
            raise ToolValidationError("query or topic is required for wikipedia lookups")

        language = str(inputs.get("language", "en")).strip().lower()
        client = self._client or httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT})
        close_client = self._client is None

        try:
            if action == "summary":
                # Wikipedia REST API v1 page summary endpoint
                encoded_title = urllib.parse.quote(query.replace(" ", "_"))
                url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
                resp = await client.get(url, follow_redirects=True)

                if resp.status_code == 200:
                    data = resp.json()
                    extract = data.get("extract", "")
                    title = data.get("title", query)
                    output = {
                        "query": query,
                        "title": title,
                        "summary": extract,
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    }
                    evidence = EvidenceItem(
                        type="tool_result",
                        summary=f"Wikipedia summary for '{title}'",
                        data=output,
                    )
                    return ToolResult.completed(
                        f"Wikipedia ({title}): {extract}",
                        output=output,
                        evidence=[evidence],
                    )

                # Fallback to search if direct title not found
                search_url = f"https://{language}.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(query)}&limit=3&namespace=0&format=json"
                search_resp = await client.get(search_url)
                if search_resp.status_code == 200:
                    s_data = search_resp.json()
                    titles = s_data[1] if len(s_data) > 1 else []
                    descriptions = s_data[2] if len(s_data) > 2 else []
                    if titles and descriptions and descriptions[0]:
                        output = {"query": query, "title": titles[0], "summary": descriptions[0]}
                        evidence = EvidenceItem(
                            type="tool_result",
                            summary=f"Wikipedia summary for '{titles[0]}'",
                            data=output,
                        )
                        return ToolResult.completed(
                            f"Wikipedia ({titles[0]}): {descriptions[0]}",
                            output=output,
                            evidence=[evidence],
                        )

                return ToolResult(
                    success=False,
                    status=ToolStatus.FAILED,
                    summary=f"Could not find Wikipedia entry for '{query}'",
                    error=f"HTTP status {resp.status_code}",
                )

            elif action == "search":
                limit = int(inputs.get("limit", 5))
                search_url = f"https://{language}.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(query)}&limit={limit}&namespace=0&format=json"
                resp = await client.get(search_url)
                if resp.status_code == 200:
                    data = resp.json()
                    titles = data[1] if len(data) > 1 else []
                    output = {"query": query, "results": titles}
                    evidence = EvidenceItem(
                        type="tool_result",
                        summary=f"Wikipedia search results for '{query}'",
                        data=output,
                    )
                    return ToolResult.completed(
                        f"Found {len(titles)} Wikipedia results for '{query}': {', '.join(titles)}",
                        output=output,
                        evidence=[evidence],
                    )
                return ToolResult(
                    success=False,
                    status=ToolStatus.FAILED,
                    summary=f"Wikipedia search failed for '{query}'",
                    error=f"HTTP status {resp.status_code}",
                )

            else:
                raise ToolValidationError(f"Unsupported wikipedia action: '{action}'. Use 'summary' or 'search'.")

        finally:
            if close_client:
                await client.aclose()

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "Wikipedia REST API ready"}
