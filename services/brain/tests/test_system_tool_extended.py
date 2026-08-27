"""Unit tests for extended actions in SystemTool (battery, volume, lock, ping)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools_builtin.system import SystemTool


@pytest.mark.asyncio
async def test_system_tool_battery():
    tool = SystemTool()
    mock_bat = MagicMock()
    mock_bat.percent = 88
    mock_bat.power_plugged = True
    mock_bat.secsleft = -1

    with patch("psutil.sensors_battery", return_value=mock_bat):
        result = await tool.execute({"action": "battery"}, context=None)
        assert result.success is True
        assert result.structured_output["percent"] == 88
        assert result.structured_output["power_plugged"] is True
        assert result.structured_output["state"] == "plugged in"


@pytest.mark.asyncio
async def test_system_tool_volume():
    tool = SystemTool()
    with patch("pyautogui.press") as mock_press:
        result = await tool.execute({"action": "volume", "direction": "up", "steps": 3}, context=None)
        assert result.success is True
        assert result.structured_output["volume_action"] == "increased"
        assert mock_press.call_count == 3


@pytest.mark.asyncio
async def test_system_tool_lock():
    tool = SystemTool()
    with patch("ctypes.windll.user32.LockWorkStation") as mock_lock:
        with patch("os.name", "nt"):
            result = await tool.execute({"action": "lock"}, context=None)
            assert result.success is True
            assert result.structured_output["lock_action"] == "workstation_locked"
            mock_lock.assert_called_once()
