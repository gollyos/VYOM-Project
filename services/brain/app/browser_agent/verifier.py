from __future__ import annotations

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult


class BrowserAgentVerifier:
    """A click on a control is never completion evidence by itself. Callers
    verify observable page state after every consequential action."""

    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def verify_state(
        self,
        context: ToolContext,
        *,
        expected_text: str | None = None,
        expected_url: str | None = None,
    ) -> ToolResult:
        return await self.executor.invoke(
            "browser",
            {"action": "read", "expected_text": expected_text, "expected_url": expected_url},
            context,
        )

    @staticmethod
    def confirms_consequential_action(result: ToolResult) -> bool:
        return bool(result.success and result.evidence)
