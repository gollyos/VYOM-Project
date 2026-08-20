from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.approvals import PermissionLevel

from .context import ToolContext
from .result import ToolResult


class ToolMetadata(BaseModel):
    name: str
    description: str
    category: str
    version: str = "1.0.0"
    required_permissions: list[PermissionLevel] = Field(default_factory=lambda: [PermissionLevel.L0])
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    supports_dry_run: bool = True
    supports_verification: bool = True
    supports_cancellation: bool = True
    risk_level: str = "low"


class BaseTool(ABC):
    metadata: ToolMetadata

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return max(self.metadata.required_permissions, key=lambda level: int(level.value[1]))

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        context.check_cancelled()

    async def dry_run(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        return ToolResult.completed(f"{self.metadata.name} validation passed", output={"dry_run": True})

    @abstractmethod
    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    async def cancel(self, context: ToolContext) -> None:
        context.cancellation_event.set()

    async def verify(
        self,
        inputs: dict[str, Any],
        result: ToolResult,
        context: ToolContext,
    ) -> ToolResult:
        context.check_cancelled()
        return result

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "available"}
