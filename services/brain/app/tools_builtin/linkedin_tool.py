from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class LinkedInTool(BaseTool):
    """Post a text update to LinkedIn. L2 — leaves VYOM's control
    boundary and reaches a public external platform, same tier as
    Instagram or sending an email."""

    metadata = ToolMetadata(
        name="linkedin",
        description=(
            "Post a text update to LinkedIn: text (the post body). "
            "Requires LinkedIn to be connected first. L2 — requires explicit approval."
        ),
        category="content",
        required_permissions=[PermissionLevel.L2],
        risk_level="high",
    )

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L2

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        from app.linkedin.schemas import LinkedInPostRequest

        text = str(inputs.get("text", "")).strip()
        if not text:
            raise ToolValidationError("text is required")
        request = LinkedInPostRequest(text=text)
        receipt = await self.service.post(request)
        return ToolResult.completed(
            f"Posted to LinkedIn: {receipt.permalink or receipt.post_id}",
            output=receipt.model_dump(mode="json"),
            evidence=[EvidenceItem(
                type="tool_result", summary="LinkedIn post",
                data={"post_id": receipt.post_id, "permalink": receipt.permalink},
            )],
        )

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
