from __future__ import annotations

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult

from .session_memory import SessionMemory


class BrowserNavigator:
    """Navigation through the registered browser tool, so every navigation
    still passes through the Permission Engine and evidence collector."""

    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def navigate(self, url: str, context: ToolContext, memory: SessionMemory) -> ToolResult:
        result = await self.executor.invoke("browser", {"action": "open", "url": url}, context)
        if result.success:
            memory.record_navigation(str(result.structured_output.get("url", url)))
        memory.record_action("navigate", {"url": url}, result.success)
        return result
