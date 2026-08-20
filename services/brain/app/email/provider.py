from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.integrations.provider import IntegrationProvider

from .schemas import EmailAddress, EmailDraft, EmailMessage, EmailThread, SendReceipt


class EmailProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]: ...

    @abstractmethod
    async def read_thread(self, thread_id: str) -> EmailThread: ...

    @abstractmethod
    async def send(self, draft: EmailDraft) -> SendReceipt: ...


class DisconnectedEmailProvider(EmailProvider):
    id = "email.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Email integration is disconnected"

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        raise RuntimeError("Email integration is disconnected")

    async def read_thread(self, thread_id: str) -> EmailThread:
        raise RuntimeError("Email integration is disconnected")

    async def send(self, draft: EmailDraft) -> SendReceipt:
        raise RuntimeError("Email integration is disconnected")


class GmailProvider(DisconnectedEmailProvider):
    """Gmail contract. Network/OAuth transport is intentionally disabled until configured."""

    id = "gmail"


class MockEmailProvider(EmailProvider):
    """Safe deterministic provider for tests and explicit demos only."""

    id = "mock-email"

    def __init__(self, messages: list[EmailMessage] | None = None) -> None:
        self.messages = list(messages or [])
        self.sent: list[EmailDraft] = []

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def begin_oauth(self, state: str) -> str:
        return f"https://mock.invalid/oauth?state={state}"

    async def complete_oauth(self, code: str) -> dict:
        if code != "mock-code":
            raise RuntimeError("Mock OAuth code rejected")
        return {"access_token": "test-fixture-access", "refresh_token": "test-fixture-refresh", "token_type": "Bearer"}

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        terms = query.casefold().split()
        matches = [
            message for message in self.messages
            if not terms or all(term in f"{message.subject} {message.body_text} {message.sender.address}".casefold() for term in terms)
        ]
        return matches[:limit]

    async def read_thread(self, thread_id: str) -> EmailThread:
        messages = [item for item in self.messages if item.thread_id == thread_id]
        if not messages:
            raise KeyError(thread_id)
        participants: dict[str, EmailAddress] = {}
        for message in messages:
            participants[message.sender.address] = message.sender
            for address in message.to:
                participants[address.address] = address
        return EmailThread(id=thread_id, subject=messages[0].subject, participants=list(participants.values()), messages=messages, provider=self.id)

    async def send(self, draft: EmailDraft) -> SendReceipt:
        self.sent.append(draft)
        suffix = len(self.sent)
        return SendReceipt(
            provider=self.id,
            message_id=f"mock-message-{suffix}",
            thread_id=draft.thread_id or f"mock-thread-{suffix}",
            sent_at=datetime.now(timezone.utc),
            verified=True,
            evidence=[f"provider_message_id:mock-message-{suffix}", f"provider_thread_id:{draft.thread_id or f'mock-thread-{suffix}'}"],
        )
