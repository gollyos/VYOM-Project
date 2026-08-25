from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class DiscordTool(BaseTool):
    """Send messages to a Discord channel and list guilds (servers) the
    bot has joined, over the SAME DiscordService the REST API uses.
    Sending is L1 — same tier as Telegram, not Instagram's L2 — because a
    Discord bot message only reaches a server VYOM's bot has already been
    invited into (a channel VYOM already knows about), not the general
    public, so there's no draft/approval workflow being bypassed."""

    metadata = ToolMetadata(
        name="discord",
        description="Send messages to a Discord channel and list guilds the bot belongs to. Reads are L0; sending is L1.",
        category="communication",
        required_permissions=[PermissionLevel.L0, PermissionLevel.L1],
        risk_level="medium",
    )

    READ_ACTIONS = {"list_guilds"}

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        return PermissionLevel.L0 if action in self.READ_ACTIONS else PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", ""))

        if action == "send":
            channel_id = str(inputs.get("channel_id", ""))
            content = str(inputs.get("content", ""))
            if not channel_id or not content:
                raise ToolValidationError("channel_id and content are required")
            receipt = await self.service.send(channel_id, content)
            return ToolResult.completed(
                f"Sent Discord message to channel {channel_id}", output=receipt.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Discord message sent",
                                       data={"message_id": receipt.message_id, "channel_id": receipt.channel_id})],
            )

        if action == "list_guilds":
            guilds = await self.service.list_guilds()
            return ToolResult.completed(
                f"{len(guilds)} guild(s)", output={"guilds": [guild.model_dump(mode="json") for guild in guilds]},
            )

        raise ToolValidationError(f"Unsupported discord action: {action}")

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
