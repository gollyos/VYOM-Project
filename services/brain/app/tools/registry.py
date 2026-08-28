from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.config import expand_environment

from .base import BaseTool
from .errors import ToolUnavailableError


class ToolRegistry:
    def __init__(self, configuration: dict[str, Any] | None = None):
        self.configuration = configuration or {"tools": {}}
        self._tools: dict[str, BaseTool] = {}

    @classmethod
    def from_yaml(cls, path: Path) -> "ToolRegistry":
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        return cls(expand_environment(raw))

    def register(self, tool: BaseTool) -> None:
        configured = self.configuration.get("tools", {}).get(tool.metadata.name, {})
        if configured.get("enabled", True):
            self._tools[tool.metadata.name] = tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def unregister_prefix(self, prefix: str) -> list[str]:
        """Remove every registered tool whose name starts with `prefix`.
        Used when an MCP server disconnects: its adapters (`mcp.<id>.*`)
        must stop being offered to the planner immediately."""
        removed = [name for name in self._tools if name.startswith(prefix)]
        for name in removed:
            self._tools.pop(name, None)
        return removed

    def get(self, name: str) -> BaseTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolUnavailableError(f"Tool '{name}' is not registered or enabled")
        return tool

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    def find_relevant_tools(self, query: str, limit: int = 8, category: str | None = None) -> list[dict[str, Any]]:
        """Intelligent semantic and keyword tool search returning top-matching active tools."""
        q = (query or "").lower().strip()
        scored: list[tuple[float, BaseTool]] = []
        words = [w for w in q.replace(".", " ").replace("_", " ").replace("-", " ").split() if len(w) > 2]

        for tool in self._tools.values():
            meta = tool.metadata
            if category and meta.category.lower() != category.lower():
                continue
            
            score = 0.0
            name_norm = meta.name.lower().replace(".", " ").replace("_", " ")
            desc_norm = meta.description.lower()

            # Exact or prefix match
            if q in meta.name.lower() or meta.name.lower() in q:
                score += 15.0
            
            for word in words:
                if word in name_norm:
                    score += 5.0
                elif word in desc_norm:
                    score += 2.0
                elif word in meta.category.lower():
                    score += 3.0

            if not q or score > 0:
                scored.append((score, tool))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, tool in scored[:limit]:
            results.append(tool.metadata.model_dump(mode="json"))
        return results

    async def describe(self) -> list[dict[str, Any]]:
        descriptions = []
        for tool in self.list():
            descriptions.append({
                **tool.metadata.model_dump(mode="json"),
                "health": await tool.health(),
            })
        return descriptions
