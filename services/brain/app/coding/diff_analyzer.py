from __future__ import annotations

from pathlib import Path

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult


class DiffAnalyzer:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def inspect(self, root: Path, context: ToolContext, paths: list[str] | None = None) -> ToolResult:
        return await self.executor.invoke(
            "git", {"action": "diff", "cwd": str(root), "paths": paths or []}, context
        )
