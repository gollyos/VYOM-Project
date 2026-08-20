from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel

from .errors import ToolCancelledError


EventEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _noop_emit(_event: str, _message: str, _payload: dict[str, Any]) -> None:
    return None


@dataclass(slots=True)
class ToolContext:
    task_id: str
    permission_level: PermissionLevel
    allowed_roots: tuple[Path, ...]
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    emit: EventEmitter = _noop_emit
    metadata: dict[str, Any] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        if self.cancellation_event.is_set():
            raise ToolCancelledError("Tool execution was cancelled")
