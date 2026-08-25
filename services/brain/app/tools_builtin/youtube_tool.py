from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class YouTubeTool(BaseTool):
    """Upload a real video file to YouTube. L2 (same tier as sending an
    email) — this leaves VYOM's control boundary and reaches a public
    external platform, so it requires explicit approval exactly like a
    send. Defaults to privacy_status='private' so an approved upload
    never becomes public without the user separately choosing that."""

    metadata = ToolMetadata(
        name="youtube",
        description=(
            "Upload a video file to YouTube (title, description, tags, privacy_status). "
            "Requires YouTube to be connected via OAuth first. L2 — requires explicit approval."
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
        from app.youtube.schemas import YouTubeUploadRequest

        video_path = str(inputs.get("video_path", "")).strip()
        title = str(inputs.get("title", "")).strip()
        if not video_path:
            raise ToolValidationError("video_path is required")
        if not title:
            raise ToolValidationError("title is required")
        request = YouTubeUploadRequest(
            video_path=video_path, title=title,
            description=str(inputs.get("description", "")),
            tags=list(inputs.get("tags", [])),
            privacy_status=str(inputs.get("privacy_status", "private")),
        )
        receipt = await self.service.upload(request)
        return ToolResult.completed(
            f"Uploaded '{title}' to YouTube: {receipt.url} ({receipt.privacy_status})",
            output=receipt.model_dump(mode="json"),
            evidence=[EvidenceItem(
                type="tool_result", summary="YouTube upload",
                data={"video_id": receipt.video_id, "url": receipt.url},
            )],
        )

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
