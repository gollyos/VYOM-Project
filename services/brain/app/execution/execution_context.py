from __future__ import annotations

import asyncio
from pathlib import Path

from app.schemas.approvals import PermissionLevel
from app.tools.context import EventEmitter, ToolContext


class ExecutionContextFactory:
    def __init__(self, allowed_roots: list[Path]):
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self._cancellations: dict[str, asyncio.Event] = {}

    def create(
        self,
        task_id: str,
        permission_level: PermissionLevel,
        emit: EventEmitter,
    ) -> ToolContext:
        cancellation = self._cancellations.setdefault(task_id, asyncio.Event())
        return ToolContext(
            task_id=task_id,
            permission_level=permission_level,
            allowed_roots=self.allowed_roots,
            cancellation_event=cancellation,
            emit=emit,
        )

    def cancel(self, task_id: str) -> None:
        self._cancellations.setdefault(task_id, asyncio.Event()).set()

    def release(self, task_id: str) -> None:
        self._cancellations.pop(task_id, None)
