from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .telegram_schemas import SendMessageRequest, SendReceipt, TelegramChat, TelegramMessage


class TelegramProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def send(self, request: SendMessageRequest) -> SendReceipt: ...

    @abstractmethod
    async def get_updates(self, offset: int | None = None, limit: int = 20) -> list[TelegramMessage]: ...

    @abstractmethod
    async def list_chats(self) -> list[TelegramChat]: ...


class DisconnectedTelegramProvider(TelegramProvider):
    id = "telegram.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Telegram integration is disconnected"

    async def send(self, request: SendMessageRequest) -> SendReceipt:
        raise RuntimeError("Telegram integration is disconnected")

    async def get_updates(self, offset: int | None = None, limit: int = 20) -> list[TelegramMessage]:
        raise RuntimeError("Telegram integration is disconnected")

    async def list_chats(self) -> list[TelegramChat]:
        raise RuntimeError("Telegram integration is disconnected")


class RealTelegramProvider(DisconnectedTelegramProvider):
    """Real Telegram Bot API integration. Unlike Gmail/Sheets, Telegram
    bots authenticate with a single bot token (from @BotFather) rather than
    OAuth — no consent-screen flow, no PKCE. A user connects VYOM's bot by
    (1) opening the bot's t.me link or scanning its QR code, which are both
    just encodings of the SAME https://t.me/<bot_username> URL, and (2)
    sending it a message; VYOM then knows their chat_id from that message
    and can message them going forward. This class is real and reachable
    once a bot_token is provided; the QR/link generation lives in
    app/api/telegram.py so the desktop UI can render it."""

    id = "telegram"

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self._client: httpx.AsyncClient | None = None
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def disconnect(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health(self) -> tuple[bool, str | None]:
        try:
            response = await self._pooled().get(f"{self._base_url}/getMe")
        except Exception as error:
            return False, f"Telegram health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, f"Telegram returned HTTP {response.status_code} — check the bot token"
        data = response.json()
        if not data.get("ok"):
            return False, data.get("description", "Telegram API returned ok=false")
        return True, None

    async def get_bot_username(self) -> str:
        response = await self._pooled().get(f"{self._base_url}/getMe")
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram getMe failed: HTTP {response.status_code}")
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram getMe returned ok=false"))
        return data["result"]["username"]

    async def send(self, request: SendMessageRequest) -> SendReceipt:
        payload: dict[str, Any] = {"chat_id": request.chat_id, "text": request.text}
        if request.parse_mode:
            payload["parse_mode"] = request.parse_mode
        response = await self._pooled().post(f"{self._base_url}/sendMessage", json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram sendMessage failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage rejected: {data.get('description', 'unknown error')}")
        result = data["result"]
        return SendReceipt(
            provider=self.id, message_id=str(result["message_id"]), chat_id=str(result["chat"]["id"]),
            sent_at=datetime.now(timezone.utc), verified=True,
        )

    async def get_updates(self, offset: int | None = None, limit: int = 20) -> list[TelegramMessage]:
        params: dict[str, Any] = {"limit": min(limit, 100), "timeout": 0}
        if offset is not None:
            params["offset"] = offset
        response = await self._pooled().get(f"{self._base_url}/getUpdates", params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram getUpdates failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates rejected: {data.get('description', 'unknown error')}")
        messages: list[TelegramMessage] = []
        for update in data.get("result", []):
            message = update.get("message") or update.get("edited_message")
            if not message or "text" not in message:
                continue
            sender = message.get("from", {})
            sender_name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])) or sender.get("username")
            messages.append(TelegramMessage(
                message_id=str(message["message_id"]), chat_id=str(message["chat"]["id"]),
                text=message["text"], sender_name=sender_name,
                sent_at=datetime.fromtimestamp(message.get("date", 0), tz=timezone.utc),
            ))
        return messages

    async def list_chats(self) -> list[TelegramChat]:
        # Telegram's Bot API has no "list all chats the bot has seen"
        # endpoint — the only source of truth is chats observed via
        # get_updates. Callers that need a persistent chat directory should
        # record chat_ids from get_updates() into their own store (see
        # app/messaging/service.py's TelegramService, which does this).
        messages = await self.get_updates(limit=100)
        seen: dict[str, TelegramChat] = {}
        for message in messages:
            seen[message.chat_id] = TelegramChat(chat_id=message.chat_id, title=message.sender_name)
        return list(seen.values())


class MockTelegramProvider(TelegramProvider):
    """Safe deterministic provider for tests and explicit demos only."""

    id = "mock-telegram"

    def __init__(self) -> None:
        self.sent: list[SendMessageRequest] = []
        self.inbound: list[TelegramMessage] = []
        self._counter = 0

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def send(self, request: SendMessageRequest) -> SendReceipt:
        self.sent.append(request)
        self._counter += 1
        return SendReceipt(
            provider=self.id, message_id=f"mock-msg-{self._counter}", chat_id=request.chat_id,
            sent_at=datetime.now(timezone.utc), verified=True,
        )

    async def get_updates(self, offset: int | None = None, limit: int = 20) -> list[TelegramMessage]:
        return self.inbound[:limit]

    async def list_chats(self) -> list[TelegramChat]:
        seen: dict[str, TelegramChat] = {}
        for message in self.inbound:
            seen[message.chat_id] = TelegramChat(chat_id=message.chat_id, title=message.sender_name)
        return list(seen.values())
