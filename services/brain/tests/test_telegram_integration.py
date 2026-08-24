"""Tests for the Telegram bot integration added this session: the real Bot
API provider (RealTelegramProvider), the chat-directory service built on
top of it (Telegram's Bot API has no 'list chats' endpoint), and the QR/
t.me-link connect flow. Uses httpx.MockTransport against realistically-
shaped Telegram Bot API responses.
"""
from __future__ import annotations

import httpx
import pytest

from app.messaging.telegram_provider import DisconnectedTelegramProvider, MockTelegramProvider, RealTelegramProvider
from app.messaging.telegram_schemas import SendMessageRequest, TelegramMessage
from app.persistence.database import Database


@pytest.mark.asyncio
async def test_real_provider_health_ok_when_get_me_succeeds():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "getMe" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "vyom_test_bot"}})

    provider = RealTelegramProvider("fake-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is True
    assert error is None
    await provider.disconnect()


@pytest.mark.asyncio
async def test_real_provider_health_reports_bad_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    provider = RealTelegramProvider("bad-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    healthy, error = await provider.health()
    assert healthy is False
    assert "401" in error
    await provider.disconnect()


@pytest.mark.asyncio
async def test_get_bot_username_for_connect_link():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "vyom_assistant_bot"}})

    provider = RealTelegramProvider("fake-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    username = await provider.get_bot_username()
    assert username == "vyom_assistant_bot"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_send_builds_correct_telegram_api_call():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "ok": True, "result": {"message_id": 42, "chat": {"id": 999}, "text": "hi"},
        })

    provider = RealTelegramProvider("fake-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    receipt = await provider.send(SendMessageRequest(chat_id="999", text="hi there"))

    assert receipt.message_id == "42"
    assert receipt.chat_id == "999"
    assert receipt.verified is True
    assert captured["body"]["chat_id"] == "999"
    assert captured["body"]["text"] == "hi there"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_get_updates_parses_real_shaped_telegram_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "ok": True,
            "result": [
                {
                    "update_id": 1001,
                    "message": {
                        "message_id": 5, "date": 1700000000,
                        "chat": {"id": 555, "type": "private"},
                        "from": {"id": 1, "first_name": "Gunjan", "username": "gunjan"},
                        "text": "gmail add karna hai",
                    },
                },
                {"update_id": 1002, "message": {"message_id": 6, "date": 1700000010, "chat": {"id": 555}, "from": {}, "text": "test 2"}},
            ],
        })

    provider = RealTelegramProvider("fake-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    messages = await provider.get_updates()

    assert len(messages) == 2
    assert messages[0].text == "gmail add karna hai"
    assert messages[0].chat_id == "555"
    assert messages[0].sender_name == "Gunjan"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_send_raises_clear_error_on_api_rejection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    provider = RealTelegramProvider("fake-token")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="400"):
        await provider.send(SendMessageRequest(chat_id="doesnotexist", text="hi"))
    await provider.disconnect()


@pytest.mark.asyncio
async def test_disconnected_provider_fails_closed_on_every_operation():
    provider = DisconnectedTelegramProvider()
    healthy, error = await provider.health()
    assert healthy is False
    with pytest.raises(RuntimeError):
        await provider.send(SendMessageRequest(chat_id="1", text="x"))
    with pytest.raises(RuntimeError):
        await provider.get_updates()
    with pytest.raises(RuntimeError):
        await provider.list_chats()


@pytest.mark.asyncio
async def test_telegram_service_builds_chat_directory_from_polled_messages(tmp_path):
    from app.messaging.telegram_service import TelegramService

    database = Database(tmp_path / "telegram_test.db")
    await database.connect()
    from app.migrations.manager import MigrationManager
    await MigrationManager(database).apply_pending()

    provider = MockTelegramProvider()
    provider.inbound = [
        TelegramMessage(message_id="1", chat_id="111", text="hello", sender_name="Alice"),
        TelegramMessage(message_id="2", chat_id="222", text="hi", sender_name="Bob"),
    ]
    service = TelegramService(database, provider)

    messages = await service.poll_and_record(limit=20)
    assert len(messages) == 2

    known = await service.list_known_chats()
    chat_ids = {c.chat_id for c in known}
    assert chat_ids == {"111", "222"}

    receipt = await service.send("111", "reply!")
    assert receipt.verified is True
    assert provider.sent[0].text == "reply!"

    await database.connection.close()
