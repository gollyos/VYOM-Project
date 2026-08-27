"""Unit tests for built-in WhatsAppTool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.errors import ToolValidationError
from app.tools_builtin.whatsapp_tool import WhatsAppTool, clean_phone_number


def test_clean_phone_number():
    assert clean_phone_number("9876543210") == "+919876543210"
    assert clean_phone_number("+919876543210") == "+919876543210"
    assert clean_phone_number("919876543210") == "+919876543210"


@pytest.mark.asyncio
async def test_whatsapp_tool_metadata():
    tool = WhatsAppTool()
    assert tool.metadata.name == "whatsapp"
    assert tool.permission_for({}) == PermissionLevel.L2


@pytest.mark.asyncio
async def test_whatsapp_send_success():
    tool = WhatsAppTool()
    with patch("pywhatkit.sendwhatmsg_instantly") as mock_send:
        result = await tool.execute(
            {"action": "send_message", "to": "9876543210", "body": "Hello from VYOM"},
            context=None,
        )
        assert result.success is True
        assert "Sent WhatsApp message to +919876543210" in result.summary
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_whatsapp_missing_params():
    tool = WhatsAppTool()
    with pytest.raises(ToolValidationError):
        await tool.execute({"action": "send_message", "to": ""}, context=None)
