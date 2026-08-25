from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class InstagramTool(BaseTool):
    """Post to Instagram (image/reel/story). L2 — leaves VYOM's control
    boundary and reaches a public external platform, same tier as
    sending an email or uploading to YouTube."""

    metadata = ToolMetadata(
        name="instagram",
        description=(
            "Post to Instagram: media_url (a PUBLIC https URL — Instagram fetches it "
            "itself, a local file path will not work), media_type (IMAGE/REELS/STORIES), "
            "caption. Requires Instagram to be connected first. L2 — requires explicit approval."
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
        from app.instagram.schemas import InstagramPostRequest

        media_url = str(inputs.get("media_url", "")).strip()
        if not media_url:
            raise ToolValidationError("media_url is required (must be a public https URL)")
        if not media_url.startswith("https://"):
            raise ToolValidationError(
                "media_url must be a public https URL — Instagram fetches the media itself; "
                "a local file path will never work here"
            )
        request = InstagramPostRequest(
            media_url=media_url, media_type=str(inputs.get("media_type", "IMAGE")),
            caption=str(inputs.get("caption", "")),
        )
        receipt = await self.service.post(request)
        return ToolResult.completed(
            f"Posted to Instagram: {receipt.permalink or receipt.media_id}",
            output=receipt.model_dump(mode="json"),
            evidence=[EvidenceItem(
                type="tool_result", summary="Instagram post",
                data={"media_id": receipt.media_id, "permalink": receipt.permalink},
            )],
        )

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
