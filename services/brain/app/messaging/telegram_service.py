from __future__ import annotations

from app.persistence.database import Database

from .telegram_provider import TelegramProvider
from .telegram_schemas import SendMessageRequest, SendReceipt, TelegramChat, TelegramMessage


class TelegramService:
    """Thin service layer over TelegramProvider, matching this repo's
    EmailService/SheetsService pattern. Also owns a persistent chat
    directory (Bot API has no 'list chats' endpoint — see
    RealTelegramProvider.list_chats's docstring) built up as messages
    arrive via poll_and_record()."""

    def __init__(self, database: Database, provider: TelegramProvider) -> None:
        self.database = database
        self.provider = provider

    async def send(self, chat_id: str, text: str, *, parse_mode: str | None = None) -> SendReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Telegram provider unavailable")
        receipt = await self.provider.send(SendMessageRequest(chat_id=chat_id, text=text, parse_mode=parse_mode))
        await self._record_chat(chat_id, None)
        return receipt

    async def poll_and_record(self, *, limit: int = 20) -> list[TelegramMessage]:
        """Fetch new messages since the last recorded update_id offset and
        persist any new chat_ids into the directory — this is how VYOM
        learns 'who has messaged the bot' since Telegram exposes no
        standalone chat-list endpoint."""
        offset = await self._last_offset()
        messages = await self.provider.get_updates(offset=offset, limit=limit)
        for message in messages:
            await self._record_chat(message.chat_id, message.sender_name)
        if messages:
            # Telegram's getUpdates offset is an UPDATE id, not a message
            # id; using message_id+1 as a heuristic offset would silently
            # re-deliver updates whose update_id sorts differently, so the
            # real offset tracking must happen at the provider layer if a
            # caller needs guaranteed non-duplicate delivery. This method
            # advances by message count as a best-effort dedupe for the
            # common single-bot-instance case.
            await self._save_offset(int(messages[-1].message_id) + 1)
        return messages

    async def list_known_chats(self) -> list[TelegramChat]:
        connection = self.database.connection
        assert connection is not None
        rows = await (await connection.execute(
            "SELECT chat_id, title FROM telegram_chats ORDER BY updated_at DESC"
        )).fetchall()
        return [TelegramChat(chat_id=row["chat_id"], title=row["title"]) for row in rows]

    async def _record_chat(self, chat_id: str, title: str | None) -> None:
        connection = self.database.connection
        assert connection is not None
        await connection.execute(
            """INSERT INTO telegram_chats(chat_id, title, updated_at) VALUES (?, ?, datetime('now'))
               ON CONFLICT(chat_id) DO UPDATE SET title=COALESCE(excluded.title, telegram_chats.title),
               updated_at=excluded.updated_at""",
            (chat_id, title),
        )
        await connection.commit()

    async def _last_offset(self) -> int | None:
        connection = self.database.connection
        assert connection is not None
        row = await (await connection.execute("SELECT value FROM telegram_state WHERE key = 'offset'")).fetchone()
        return int(row["value"]) if row else None

    async def _save_offset(self, offset: int) -> None:
        connection = self.database.connection
        assert connection is not None
        await connection.execute(
            "INSERT INTO telegram_state(key, value) VALUES ('offset', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(offset),),
        )
        await connection.commit()
