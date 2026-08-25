from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx

from app.integrations.provider import IntegrationProvider

from .discord_schemas import DiscordGuild, DiscordSendReceipt

_DISCORD_API = "https://discord.com/api/v10"


class DiscordProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def send_message(self, channel_id: str, content: str) -> DiscordSendReceipt: ...

    @abstractmethod
    async def list_guilds(self) -> list[DiscordGuild]: ...


class DisconnectedDiscordProvider(DiscordProvider):
    id = "discord.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Discord integration is disconnected"

    async def send_message(self, channel_id: str, content: str) -> DiscordSendReceipt:
        raise RuntimeError("Discord integration is disconnected")

    async def list_guilds(self) -> list[DiscordGuild]:
        raise RuntimeError("Discord integration is disconnected")


class RealDiscordProvider(DisconnectedDiscordProvider):
    """Real Discord Bot API integration. Like Telegram (and unlike
    Instagram/Meta Ads), a Discord bot authenticates with a single bot
    token minted once in the Developer Portal (New Application -> Bot ->
    Copy Token) — no OAuth consent-screen flow. The bot must additionally
    be invited into a server ("guild") with the Send Messages permission
    before it can post anywhere; that invite step happens out-of-band in
    Discord's own UI and isn't something this provider can drive, so
    health() can only confirm the token itself is valid, not that the bot
    has landed in a particular channel — send_message() surfaces that as
    a normal API error (e.g. missing access) rather than pretending it's
    guaranteed to work post-connect.

    Credentials are stored via the same SecretVault (Windows DPAPI) the
    Instagram provider uses, keyed by the bot's application — this is
    deliberately the same "no hand-rolled credential storage" pattern
    rather than reading straight from an env var like Telegram's
    constructor-arg approach, so the self-service /connect endpoint here
    matches Instagram's connect/disconnect/status shape exactly.
    """

    id = "discord"

    def __init__(self, vault) -> None:
        self.vault = vault
        self._client: httpx.AsyncClient | None = None

    def store_credentials(self, bot_token: str) -> None:
        payload = json.dumps({"bot_token": bot_token}).encode("utf-8")
        self.vault.set("token:discord", payload)

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("token:discord")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("token:discord")
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    def _headers(self, bot_token: str) -> dict[str, str]:
        # Discord's bot auth scheme is "Bot <token>", NOT "Bearer" — mixing
        # these up is a common integration mistake and silently returns 401.
        return {"Authorization": f"Bot {bot_token}"}

    async def health(self) -> tuple[bool, str | None]:
        creds = self._load_credentials()
        if creds is None:
            return False, "Discord is not connected"
        try:
            response = await self._pooled().get(f"{_DISCORD_API}/users/@me", headers=self._headers(creds["bot_token"]))
        except Exception as error:
            return False, f"Discord health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, self._friendly_error(response)
        return True, None

    @staticmethod
    def _friendly_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            message = data.get("message", "")
        except Exception:
            message = response.text[:200]
        return f"Discord rejected the request: {message}"[:300] or f"HTTP {response.status_code}"

    async def send_message(self, channel_id: str, content: str) -> DiscordSendReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Discord is not connected")
        response = await self._pooled().post(
            f"{_DISCORD_API}/channels/{channel_id}/messages",
            headers=self._headers(creds["bot_token"]),
            json={"content": content},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Discord sendMessage failed: {self._friendly_error(response)}")
        data = response.json()
        return DiscordSendReceipt(
            provider=self.id, message_id=str(data["id"]), channel_id=str(data["channel_id"]),
            sent_at=datetime.now(timezone.utc), verified=True,
        )

    async def list_guilds(self) -> list[DiscordGuild]:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Discord is not connected")
        response = await self._pooled().get(
            f"{_DISCORD_API}/users/@me/guilds", headers=self._headers(creds["bot_token"]),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Discord list guilds failed: {self._friendly_error(response)}")
        return [DiscordGuild(id=str(item["id"]), name=item["name"]) for item in response.json()]


class MockDiscordProvider(DiscordProvider):
    """Safe deterministic provider for tests and explicit demos only."""

    id = "mock-discord"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.guilds: list[DiscordGuild] = []
        self._counter = 0

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def send_message(self, channel_id: str, content: str) -> DiscordSendReceipt:
        self.sent.append((channel_id, content))
        self._counter += 1
        return DiscordSendReceipt(
            provider=self.id, message_id=f"mock-msg-{self._counter}", channel_id=channel_id,
            sent_at=datetime.now(timezone.utc), verified=True,
        )

    async def list_guilds(self) -> list[DiscordGuild]:
        return self.guilds
