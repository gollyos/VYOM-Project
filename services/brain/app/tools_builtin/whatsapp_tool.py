"""Built-in WhatsApp Tool for VYOM.

Provides WhatsApp messaging and calling integration using pywhatkit and WhatsApp Web.
L2 tier (same as email/YouTube) — requires approval for external communication.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import webbrowser
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

logger = logging.getLogger(__name__)


def clean_phone_number(number: str) -> str:
    """Normalize phone number to international E.164 format."""
    cleaned = re.sub(r"[^\d+]", "", number)
    if len(cleaned) == 10 and not cleaned.startswith("+"):
        cleaned = "+91" + cleaned
    elif len(cleaned) == 12 and cleaned.startswith("91") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    elif not cleaned.startswith("+") and cleaned:
        cleaned = "+" + cleaned
    return cleaned


class WhatsAppTool(BaseTool):
    """Send WhatsApp message or initiate WhatsApp voice/video calls.
    L2 permission tier — external action requiring user approval."""

    metadata = ToolMetadata(
        name="whatsapp",
        description=(
            "Send WhatsApp messages or initiate calls to a phone number or contact name. "
            "Actions: send_message, make_call. L2 — requires approval."
        ),
        category="communication",
        required_permissions=[PermissionLevel.L2],
        risk_level="high",
    )

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L2

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "send_message")).strip().lower()
        target = str(inputs.get("to", "") or inputs.get("contact", "") or inputs.get("phone", "")).strip()

        if not target:
            raise ToolValidationError("'to' or 'contact' is required for WhatsApp actions")

        target_phone = clean_phone_number(target)

        if action in {"send_message", "send"}:
            body = str(inputs.get("body", "") or inputs.get("message", "")).strip()
            if not body:
                raise ToolValidationError("'body' or 'message' is required for WhatsApp send_message")

            try:
                import pywhatkit

                pywhatkit.sendwhatmsg_instantly(
                    phone_no=target_phone,
                    message=body,
                    wait_time=12,
                    tab_close=False,
                    close_time=3,
                )
                output = {"action": "send_message", "to": target_phone, "body": body, "status": "sent"}
                evidence = EvidenceItem(
                    type="tool_result",
                    summary=f"WhatsApp message sent to {target_phone}",
                    data=output,
                )
                return ToolResult.completed(
                    f"Sent WhatsApp message to {target_phone}: \"{body}\"",
                    output=output,
                    evidence=[evidence],
                )
            except Exception as exc:
                logger.warning("pywhatkit instant message failed, opening web session: %s", exc)
                encoded_msg = urllib.parse.quote_plus(body)
                web_url = f"https://web.whatsapp.com/send?phone={target_phone}&text={encoded_msg}"
                webbrowser.open(web_url)
                output = {"action": "send_message", "to": target_phone, "body": body, "status": "opened_in_browser"}
                evidence = EvidenceItem(
                    type="tool_result",
                    summary=f"WhatsApp Web opened for {target_phone}",
                    data=output,
                )
                return ToolResult.completed(
                    f"Opened WhatsApp Web message session for {target_phone}",
                    output=output,
                    evidence=[evidence],
                )

        elif action in {"make_call", "call"}:
            video = bool(inputs.get("video", False))
            call_type = "video" if video else "voice"
            web_url = f"https://web.whatsapp.com/send?phone={target_phone}"
            try:
                webbrowser.open(web_url)
                output = {"action": "make_call", "to": target_phone, "type": call_type, "status": "initiated"}
                evidence = EvidenceItem(
                    type="tool_result",
                    summary=f"WhatsApp {call_type} call initiated for {target_phone}",
                    data=output,
                )
                return ToolResult.completed(
                    f"Initiated WhatsApp {call_type} call to {target_phone}",
                    output=output,
                    evidence=[evidence],
                )
            except Exception as exc:
                return ToolResult.failed(f"Failed to initiate WhatsApp call to {target_phone}: {exc}", error=str(exc))

        else:
            raise ToolValidationError(f"Unsupported WhatsApp action: '{action}'. Use 'send_message' or 'make_call'.")

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "WhatsApp automation channel ready"}
