from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class TelegramTool(BaseTool):
    """Send/poll/list Telegram chats, over the SAME TelegramService the
    REST API uses. Sending is L1 (a message to a chat the user already
    connected — lower risk than email's L2 send since there is no
    draft/approval workflow to bypass and the recipient is one VYOM already
    knows about, per TelegramService's chat directory)."""

    metadata = ToolMetadata(
        name="telegram",
        description="Send messages, poll for new inbound messages, and list known Telegram chats. Reads are L0; sending is L1.",
        category="communication",
        required_permissions=[PermissionLevel.L0, PermissionLevel.L1],
        risk_level="medium",
    )

    READ_ACTIONS = {"list_chats", "poll"}

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        return PermissionLevel.L0 if action in self.READ_ACTIONS else PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", ""))

        if action == "send":
            chat_id = str(inputs.get("chat_id", ""))
            text = str(inputs.get("text", ""))
            if not chat_id or not text:
                raise ToolValidationError("chat_id and text are required")
            receipt = await self.service.send(chat_id, text, parse_mode=inputs.get("parse_mode"))
            return ToolResult.completed(
                f"Sent Telegram message to {chat_id}", output=receipt.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Telegram message sent",
                                       data={"message_id": receipt.message_id, "chat_id": receipt.chat_id})],
            )

        if action == "poll":
            limit = int(inputs.get("limit", 20))
            messages = await self.service.poll_and_record(limit=limit)
            return ToolResult.completed(
                f"{len(messages)} new message(s)", output={"messages": [m.model_dump(mode="json") for m in messages]},
                evidence=[EvidenceItem(type="tool_result", summary="Telegram poll", data={"count": len(messages)})],
            )

        if action == "list_chats":
            chats = await self.service.list_known_chats()
            return ToolResult.completed(
                f"{len(chats)} known chat(s)", output={"chats": [chat.model_dump(mode="json") for chat in chats]},
            )

        raise ToolValidationError(f"Unsupported telegram action: {action}")

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
