from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class FacebookTool(BaseTool):
    """Post to a Facebook Page (text, link, or photo). L2 — leaves
    VYOM's control boundary and reaches a public external platform,
    same tier as Instagram/Twitter/email."""

    metadata = ToolMetadata(
        name="facebook",
        description=(
            "Post to a Facebook Page: message (text), optional link (Facebook fetches its own "
            "preview), or photo_url (a PUBLIC https URL — Facebook fetches it itself). "
            "Requires Facebook to be connected first. L2 — requires explicit approval."
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
        from app.facebook.schemas import FacebookPostRequest

        message = str(inputs.get("message", "")).strip()
        link = inputs.get("link")
        photo_url = inputs.get("photo_url")
        if not message and not link and not photo_url:
            raise ToolValidationError("At least one of message, link, or photo_url is required")
        if photo_url and not str(photo_url).startswith("https://"):
            raise ToolValidationError(
                "photo_url must be a public https URL — Facebook fetches the media itself; "
                "a local file path will never work here"
            )
        request = FacebookPostRequest(
            message=message, link=str(link) if link else None, photo_url=str(photo_url) if photo_url else None,
        )
        receipt = await self.service.post(request)
        return ToolResult.completed(
            f"Posted to Facebook: {receipt.permalink or receipt.post_id}",
            output=receipt.model_dump(mode="json"),
            evidence=[EvidenceItem(
                type="tool_result", summary="Facebook post",
                data={"post_id": receipt.post_id, "permalink": receipt.permalink},
            )],
        )

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
