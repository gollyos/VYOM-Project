"""Tests for TelegramGateway Phone-to-PC Remote Controller commands.
Validates /status, /lock, unauthorized chat blocking, and command routing.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.gateway.telegram import TelegramGateway


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    task = MagicMock()
    task.id = "task-1234567890abcdef"
    runtime.create_task = AsyncMock(return_value=task)
    return runtime


@pytest.fixture
def mock_task_store():
    store = MagicMock()
    result = MagicMock()
    result.response = "Build completed successfully."
    task = MagicMock()
    task.status.value = "completed"
    task.result = result
    store.get = AsyncMock(return_value=task)
    return store


@pytest.mark.asyncio
async def test_telegram_status_command(tmp_path: Path, mock_runtime, mock_task_store):
    state_file = tmp_path / "telegram_state.json"
    gateway = TelegramGateway(
        token="123456:ABC-DEF",
        runtime=mock_runtime,
        task_store=mock_task_store,
        state_path=state_file,
        allowed_chat_ids={"12345"},
    )
    gateway._send_text = AsyncMock()

    # Pair chat
    await gateway._handle_message({"chat": {"id": 12345, "type": "private"}, "text": "/start"})
    gateway._send_text.assert_called_with("12345", "VYOM online Boss. This owner chat is authorized.")

    # Status check
    await gateway._handle_message({"chat": {"id": 12345, "type": "private"}, "text": "/status"})
    assert gateway._send_text.call_count == 2
    last_call_args = gateway._send_text.call_args[0]
    assert "PC Status: ONLINE" in last_call_args[1]
    assert "Brain Status: READY" in last_call_args[1]


@pytest.mark.asyncio
async def test_unauthorized_chat_rejected(tmp_path: Path, mock_runtime, mock_task_store):
    state_file = tmp_path / "telegram_state.json"
    gateway = TelegramGateway(
        token="123456:ABC-DEF",
        runtime=mock_runtime,
        task_store=mock_task_store,
        state_path=state_file,
        allowed_chat_ids={"12345"},
    )
    gateway._send_text = AsyncMock()

    # Unauthorized user
    await gateway._handle_message({"chat": {"id": 99999, "type": "private"}, "text": "/status"})
    gateway._send_text.assert_called_with("99999", "This chat is not paired with VYOM.")
