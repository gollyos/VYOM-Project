from __future__ import annotations

from pathlib import Path

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult


class TestRunner:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def run(self, command: str, root: Path, context: ToolContext, timeout: float = 300) -> ToolResult:
        await context.emit("test_started", f"Running {command}", {"command": command, "cwd": str(root)})
        result = await self.executor.invoke(
            "terminal", {"command": command, "cwd": str(root), "timeout": timeout}, context
        )
        await context.emit(
            "test_passed" if result.success else "test_failed",
            result.summary,
            {"command": command, "exit_code": result.structured_output.get("exit_code")},
        )
        return result
