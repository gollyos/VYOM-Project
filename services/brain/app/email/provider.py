from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any

import httpx

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


# Gmail requires exactly the scopes it needs: read (search/get), compose
# (send), and never broader ("mail.google.com" full-mailbox access) than the
# capabilities this provider actually implements.
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _decode_header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _parse_address(raw: str) -> EmailAddress:
    raw = (raw or "").strip()
    if "<" in raw and raw.endswith(">"):
        name, _, rest = raw.partition("<")
        return EmailAddress(address=rest.rstrip(">").strip(), name=name.strip().strip('"') or None)
    return EmailAddress(address=raw)


def _decode_body(payload: dict) -> str:
    """Gmail nests the body under payload.parts for multipart messages, or
    payload.body directly for simple ones. Depth-first search for the first
    text/plain part; fall back to text/html stripped of tags if that's all
    there is, since a body the user can't read is worse than a lossy one."""
    def _walk(node: dict) -> str | None:
        mime = node.get("mimeType", "")
        body = node.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        for part in node.get("parts", []) or []:
            found = _walk(part)
            if found:
                return found
        if mime == "text/html" and data:
            import re

            html = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)
        return None

    return _walk(payload) or ""


class GmailProvider(DisconnectedEmailProvider):
    """Real Gmail integration over the Gmail REST API. Network/OAuth is
    active once `google_oauth` (client_id/secret) and a stored token are
    present; until then this behaves exactly like the disconnected stub it
    replaces, per this repo's existing IntegrationProvider contract."""

    id = "gmail"

    def __init__(self, oauth_client, vault) -> None:
        self.oauth_client = oauth_client
        self.vault = vault
        self._client: httpx.AsyncClient | None = None
        #: IntegrationProvider.complete_oauth(code) receives no state (that
        #: half of the contract lives in IntegrationRegistry, which already
        #: verified it before calling here) — but GoogleOAuthClient's PKCE
        #: verifier is keyed by state, so this provider remembers the state
        #: it most recently issued in begin_oauth() to look the verifier
        #: back up. Fine for a single-user desktop app with one pending
        #: OAuth flow at a time; a concurrent second begin_oauth() call
        #: before the first completes would only affect that edge case.
        self._pending_state: str | None = None

    # -- OAuth -------------------------------------------------------------

    async def begin_oauth(self, state: str) -> str:
        self._pending_state = state
        return self.oauth_client.authorization_url(state)

    async def complete_oauth(self, code: str) -> dict[str, Any]:
        state = self._pending_state or ""
        self._pending_state = None
        token_bundle = await self.oauth_client.exchange_code(state, code)
        return token_bundle

    async def disconnect(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- token/session -------------------------------------------------------

    def _load_token(self) -> dict[str, Any] | None:
        raw = self.vault.get("oauth:gmail")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def _access_token(self) -> str:
        token = self._load_token()
        if token is None:
            raise RuntimeError("Gmail is not connected — complete OAuth first")
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        # Google access tokens expire in ~1h; a real "expired" response is
        # what actually forces the refresh (rather than tracking wall-clock
        # expiry ourselves, which drifts) — see _request()'s 401 retry.
        if not access_token and refresh_token:
            refreshed = await self.oauth_client.refresh(refresh_token)
            refreshed.setdefault("refresh_token", refresh_token)
            self.vault.set("oauth:gmail", json.dumps(refreshed).encode("utf-8"))
            return refreshed["access_token"]
        if not access_token:
            raise RuntimeError("Gmail token is missing an access_token — reconnect required")
        return access_token

    async def _refresh_and_retry(self) -> str:
        token = self._load_token() or {}
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Gmail access expired and no refresh_token is stored — reconnect required")
        refreshed = await self.oauth_client.refresh(refresh_token)
        refreshed.setdefault("refresh_token", refresh_token)
        self.vault.set("oauth:gmail", json.dumps(refreshed).encode("utf-8"))
        return refreshed["access_token"]

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        access_token = await self._access_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {access_token}"}
        response = await self._pooled().request(method, url, headers=headers, **kwargs)
        if response.status_code == 401:
            access_token = await self._refresh_and_retry()
            headers["Authorization"] = f"Bearer {access_token}"
            response = await self._pooled().request(method, url, headers=headers, **kwargs)
        return response

    # -- health --------------------------------------------------------------

    async def health(self) -> tuple[bool, str | None]:
        if self._load_token() is None:
            return False, "Gmail is not connected"
        try:
            response = await self._request("GET", f"{_GMAIL_API}/profile")
        except Exception as error:
            return False, f"Gmail health check failed: {error}"[:300]
        if response.status_code >= 400:
            return False, f"Gmail returned HTTP {response.status_code}"
        return True, None

    # -- reads -----------------------------------------------------------

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        response = await self._request(
            "GET", f"{_GMAIL_API}/messages",
            params={"q": query, "maxResults": min(limit, 100)},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail search failed: HTTP {response.status_code}: {response.text[:200]}")
        ids = [item["id"] for item in response.json().get("messages", [])]
        messages: list[EmailMessage] = []
        for message_id in ids[:limit]:
            messages.append(await self._get_message(message_id))
        return messages

    async def _get_message(self, message_id: str) -> EmailMessage:
        response = await self._request(
            "GET", f"{_GMAIL_API}/messages/{message_id}", params={"format": "full"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail get message failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        payload = data.get("payload", {})
        headers = payload.get("headers", [])
        sender = _parse_address(_decode_header(headers, "From"))
        to = [_parse_address(part) for part in _decode_header(headers, "To").split(",") if part.strip()]
        received_ms = int(data.get("internalDate", "0") or 0)
        return EmailMessage(
            id=data["id"], thread_id=data.get("threadId", data["id"]),
            sender=sender, to=to, subject=_decode_header(headers, "Subject"),
            body_text=_decode_body(payload)[:50_000],
            received_at=datetime.fromtimestamp(received_ms / 1000, tz=timezone.utc) if received_ms else datetime.now(timezone.utc),
            labels=data.get("labelIds", []), provider=self.id,
        )

    async def read_thread(self, thread_id: str) -> EmailThread:
        response = await self._request("GET", f"{_GMAIL_API}/threads/{thread_id}", params={"format": "full"})
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail read thread failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        messages: list[EmailMessage] = []
        participants: dict[str, EmailAddress] = {}
        for raw_message in data.get("messages", []):
            payload = raw_message.get("payload", {})
            headers = payload.get("headers", [])
            sender = _parse_address(_decode_header(headers, "From"))
            to = [_parse_address(part) for part in _decode_header(headers, "To").split(",") if part.strip()]
            received_ms = int(raw_message.get("internalDate", "0") or 0)
            message = EmailMessage(
                id=raw_message["id"], thread_id=thread_id, sender=sender, to=to,
                subject=_decode_header(headers, "Subject"), body_text=_decode_body(payload)[:50_000],
                received_at=datetime.fromtimestamp(received_ms / 1000, tz=timezone.utc) if received_ms else datetime.now(timezone.utc),
                labels=raw_message.get("labelIds", []), provider=self.id,
            )
            messages.append(message)
            participants[sender.address] = sender
            for address in to:
                participants[address.address] = address
        subject = messages[0].subject if messages else ""
        return EmailThread(id=thread_id, subject=subject, participants=list(participants.values()), messages=messages, provider=self.id)

    # -- writes ------------------------------------------------------------

    async def send(self, draft: EmailDraft) -> SendReceipt:
        mime = MIMEText(draft.body_text)
        mime["To"] = ", ".join(f"{a.name} <{a.address}>" if a.name else a.address for a in draft.to)
        mime["Subject"] = draft.subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        body: dict[str, Any] = {"raw": raw}
        if draft.thread_id:
            body["threadId"] = draft.thread_id
        response = await self._request("POST", f"{_GMAIL_API}/messages/send", json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail send failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        return SendReceipt(
            provider=self.id, message_id=data["id"], thread_id=data.get("threadId", data["id"]),
            sent_at=datetime.now(timezone.utc), verified=True,
            evidence=[f"provider_message_id:{data['id']}", f"provider_thread_id:{data.get('threadId', data['id'])}"],
        )


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

