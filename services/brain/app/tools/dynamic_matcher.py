"""Dynamic JIT Tool Matcher & Router for VYOM.

Enables VYOM to dynamically select, bind, and execute any of the 335+ tools in the catalog
without bloating the LLM prompt or blowing the token context window.
"""

from __future__ import annotations

import logging
from typing import Any
from app.tools.catalog_300 import (
    ALL_300_TOOLS,
    ToolDefinition,
    search_tools,
    get_tools_by_category,
    count_tools,
)

logger = logging.getLogger("vyom.tools.matcher")


class DynamicToolMatcher:
    """Intelligent semantic & lexical tool selector for 300+ tools catalog."""

    def __init__(self) -> None:
        self.catalog = ALL_300_TOOLS
        self._category_index: dict[str, list[ToolDefinition]] = {}
        for tool in self.catalog:
            self._category_index.setdefault(tool.category, []).append(tool)
        logger.info("DynamicToolMatcher initialized with %d tools across %d categories", len(self.catalog), len(self._category_index))

    def match_for_prompt(self, user_prompt: str, max_tools: int = 8) -> list[ToolDefinition]:
        """Finds the most relevant tools for a given user prompt."""
        if not user_prompt:
            return self.catalog[:max_tools]
        matched = search_tools(user_prompt, limit=max_tools)
        if not matched:
            # Fallback to general productivity & dev essentials
            matched = self.get_category_tools("productivity")[:4] + self.get_category_tools("system")[:4]
        return matched

    def get_category_tools(self, category: str) -> list[ToolDefinition]:
        """Retrieve tools for a specific domain category."""
        return self._category_index.get(category.lower(), [])

    def get_catalog_stats(self) -> dict[str, Any]:
        """Returns statistics of the 300+ tool ecosystem."""
        return count_tools()

    def get_tool_by_id(self, tool_id: str) -> ToolDefinition | None:
        """Fetch tool schema by its exact ID."""
        for tool in self.catalog:
            if tool.id == tool_id:
                return tool
        return None


# Global singleton instance
_GLOBAL_MATCHER: DynamicToolMatcher | None = None


def get_tool_matcher() -> DynamicToolMatcher:
    """Returns singleton instance of DynamicToolMatcher."""
    global _GLOBAL_MATCHER
    if _GLOBAL_MATCHER is None:
        _GLOBAL_MATCHER = DynamicToolMatcher()
    return _GLOBAL_MATCHER
