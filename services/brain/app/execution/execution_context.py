from __future__ import annotations

import asyncio
from pathlib import Path

from app.schemas.approvals import PermissionLevel
from app.tools.context import EventEmitter, ToolContext


class ExecutionContextFactory:
    def __init__(self, allowed_roots: list[Path]):
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self._cancellations: dict[str, asyncio.Event] = {}
        # Live per-task tool sequence, populated by ToolExecutor.invoke via
        # the SAME ToolContext.metadata every handler in ActionEngine
        # already shares. This is how a real, observed tool sequence
        # (not a guess) reaches the self-improvement loop for skill
        # auto-promotion — see TaskRuntime._finish_result.
        self._contexts: dict[str, ToolContext] = {}

    def create(
        self,
        task_id: str,
        permission_level: PermissionLevel,
        emit: EventEmitter,
        visibility: str | None = None,
    ) -> ToolContext:
        cancellation = self._cancellations.setdefault(task_id, asyncio.Event())
        context = ToolContext(
            task_id=task_id,
            permission_level=permission_level,
            allowed_roots=self.allowed_roots,
            cancellation_event=cancellation,
            emit=emit,
        )
        # Per-task visibility decision flows to tools via metadata. The
        # BrowserTool reads this to open a real on-screen window for a
        # 'visual' task (headless=False) instead of the default hidden
        # headless browser — see app/execution/visibility.py.
        if visibility:
            context.metadata["visibility"] = visibility
        self._contexts[task_id] = context
        return context

    def tools_used(self, task_id: str) -> list[str]:
        context = self._contexts.get(task_id)
        return list(context.metadata.get("tools_used", [])) if context else []

    def cancel(self, task_id: str) -> None:
        self._cancellations.setdefault(task_id, asyncio.Event()).set()

    def release(self, task_id: str) -> None:
        self._cancellations.pop(task_id, None)
        self._contexts.pop(task_id, None)
