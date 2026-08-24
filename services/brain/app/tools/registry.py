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

    async def describe(self) -> list[dict[str, Any]]:
        descriptions = []
        for tool in self.list():
            descriptions.append({
                **tool.metadata.model_dump(mode="json"),
                "health": await tool.health(),
            })
        return descriptions
