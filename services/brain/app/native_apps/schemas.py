from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.desktop.schemas import IntegrationType


@dataclass
class AdapterActionResult:
    success: bool
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)


class AppAdapter(ABC):
    """One native-app-specific integration. Adapters prefer native
    API/CLI/accessibility control; only a `visual_fallback` adapter falls
    back toward input automation, and even then only through the bounded
    `input_control` module (see docs/NATIVE_APP_AUTOMATION.md)."""

    app_id: str
    integration_type: IntegrationType
    supported_actions: tuple[str, ...] = ()

    @abstractmethod
    async def open(self, *, target: str | None = None) -> AdapterActionResult: ...

    async def focus(self) -> AdapterActionResult:
        raise NotImplementedError(f"{self.app_id} adapter does not support focus")

    async def close(self) -> AdapterActionResult:
        raise NotImplementedError(f"{self.app_id} adapter does not support close")

    async def status(self) -> AdapterActionResult:
        raise NotImplementedError(f"{self.app_id} adapter does not support status")
