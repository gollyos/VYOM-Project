from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IntegrationProvider(ABC):
    id: str

    @abstractmethod
    async def health(self) -> tuple[bool, str | None]: ...

    async def begin_oauth(self, state: str) -> str:
        raise RuntimeError(f"OAuth is not configured for {self.id}")

    async def complete_oauth(self, code: str) -> dict[str, Any]:
        raise RuntimeError(f"OAuth is not configured for {self.id}")

    async def disconnect(self) -> None:
        return None
