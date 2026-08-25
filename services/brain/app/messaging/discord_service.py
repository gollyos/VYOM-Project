from __future__ import annotations

from .discord_provider import DiscordProvider
from .discord_schemas import DiscordGuild, DiscordSendReceipt


class DiscordService:
    """Thin service layer over DiscordProvider, matching this repo's
    TelegramService/InstagramService pattern: the HTTP layer (provider)
    stays a dumb API client, and the service is the single place that
    enforces "don't attempt a send/read against a provider that isn't
    actually healthy" so both the REST API and the tool go through the
    same check."""

    def __init__(self, provider: DiscordProvider) -> None:
        self.provider = provider

    async def send(self, channel_id: str, content: str) -> DiscordSendReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Discord provider unavailable")
        return await self.provider.send_message(channel_id, content)

    async def list_guilds(self) -> list[DiscordGuild]:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Discord provider unavailable")
        return await self.provider.list_guilds()
