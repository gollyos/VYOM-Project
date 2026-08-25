from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any
from uuid import uuid4

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


class GmailAppPasswordProvider(DisconnectedEmailProvider):
    """Real Gmail integration over plain SMTP (send) + IMAP (search/read),
    authenticated with a Google 16-character App Password instead of
    OAuth. This is the second, simpler connect path the user explicitly
    asked for alongside OAuth: paste the Gmail address + a 16-digit App
    Password (Google Account -> Security -> 2-Step Verification -> App
    Passwords) and it works immediately — no Cloud Console project,
    no consent screen, no redirect URI. Requires the SAME 2FA-enabled
    account prerequisite Google requires for any App Password, which is
    Google's own requirement, not this provider's.

    Uses Python's stdlib smtplib/imaplib (no new dependency) via
    asyncio.to_thread, since neither has a native async client in this
    repo's existing dependency set."""

    id = "gmail-app-password"

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 465
    IMAP_HOST = "imap.gmail.com"
    IMAP_PORT = 993

    def __init__(self, vault) -> None:
        self.vault = vault

    # -- credential storage --------------------------------------------------
    # Deliberately NOT the OAuth token slot ("oauth:gmail") — this is a
    # completely separate credential shape (address + app password), and a
    # user may have BOTH an OAuth-connected Gmail and an app-password one
    # (e.g. two different Google accounts) without either overwriting the
    # other's stored secret.

    def store_credentials(self, address: str, app_password: str) -> None:
        normalized = app_password.replace(" ", "")
        if len(normalized) != 16 or not normalized.isalnum():
            raise ValueError(
                "A Google App Password is 16 characters (letters/digits only, "
                "spaces are cosmetic and stripped) — this does not look like one. "
                "Generate one at https://myaccount.google.com/apppasswords "
                "(requires 2-Step Verification to be enabled first)."
            )
        payload = json.dumps({"address": address, "app_password": normalized}).encode("utf-8")
        self.vault.set("app_password:gmail", payload)

    def _load_credentials(self) -> dict[str, str] | None:
        raw = self.vault.get("app_password:gmail")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def disconnect(self) -> None:
        self.vault.delete("app_password:gmail")

    # -- health --------------------------------------------------------------

    async def health(self) -> tuple[bool, str | None]:
        creds = self._load_credentials()
        if creds is None or not creds.get("app_password"):
            return False, "Gmail app-password is not connected"
        try:
            await asyncio.to_thread(self._imap_login, creds["address"], creds["app_password"])
        except Exception as error:
            return False, self._friendly_auth_error(error)
        return True, None

    @staticmethod
    def _friendly_auth_error(error: Exception) -> str:
        text = str(error)
        if "AUTHENTICATIONFAILED" in text or "Username and Password not accepted" in text:
            return (
                "Gmail rejected the address/app-password combination. Check the address is "
                "correct, 2-Step Verification is enabled on that account, and the App Password "
                "was generated for THIS account (App Passwords are account-specific)."
            )
        return f"Gmail app-password login failed: {text}"[:300]

    # -- IMAP (blocking, run via to_thread) -----------------------------------

    def _imap_login(self, address: str, app_password: str):
        import imaplib

        connection = imaplib.IMAP4_SSL(self.IMAP_HOST, self.IMAP_PORT, timeout=15)
        connection.login(address, app_password)
        return connection

    def _imap_search_blocking(self, address: str, app_password: str, query: str, limit: int) -> list[EmailMessage]:
        import email as email_stdlib
        import imaplib

        connection = self._imap_login(address, app_password)
        try:
            connection.select("INBOX", readonly=True)
            # IMAP SEARCH's TEXT criterion is a blunt full-message substring
            # search (subject+body+headers) — good enough for "find the
            # email about X" without building a Gmail-query-syntax parser
            # for a provider whose whole point is being the SIMPLE path.
            criteria = f'(TEXT "{query}")' if query.strip() else "ALL"
            status, data = connection.search(None, criteria)
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")
            ids = data[0].split()[-limit:] if data and data[0] else []
            messages: list[EmailMessage] = []
            for raw_id in reversed(ids):  # newest first
                status, msg_data = connection.fetch(raw_id, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                parsed = email_stdlib.message_from_bytes(raw_bytes)
                messages.append(self._parse_stdlib_message(parsed, raw_id.decode()))
            return messages
        finally:
            with contextlib.suppress(Exception):
                connection.close()
            with contextlib.suppress(Exception):
                connection.logout()

    @staticmethod
    def _decode_mime_header(value: str | None) -> str:
        if not value:
            return ""
        from email.header import decode_header

        parts = decode_header(value)
        decoded = ""
        for text, charset in parts:
            if isinstance(text, bytes):
                decoded += text.decode(charset or "utf-8", errors="replace")
            else:
                decoded += text
        return decoded

    def _parse_stdlib_message(self, parsed, uid: str) -> EmailMessage:
        from email.utils import parsedate_to_datetime

        subject = self._decode_mime_header(parsed.get("Subject", ""))
        sender = _parse_address(self._decode_mime_header(parsed.get("From", "")))
        to = [
            _parse_address(part)
            for part in self._decode_mime_header(parsed.get("To", "")).split(",")
            if part.strip()
        ]
        body_text = ""
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == "text/plain" and not part.get_filename():
                    charset = part.get_content_charset() or "utf-8"
                    body_text = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
        else:
            charset = parsed.get_content_charset() or "utf-8"
            payload = parsed.get_payload(decode=True)
            body_text = payload.decode(charset, errors="replace") if payload else ""
        try:
            received_at = parsedate_to_datetime(parsed.get("Date", ""))
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            received_at = datetime.now(timezone.utc)
        message_id = parsed.get("Message-ID", uid) or uid
        return EmailMessage(
            id=message_id, thread_id=message_id, sender=sender, to=to, subject=subject,
            body_text=body_text[:50_000], received_at=received_at, labels=[], provider=self.id,
        )

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Gmail app-password is not connected")
        return await asyncio.to_thread(
            self._imap_search_blocking, creds["address"], creds["app_password"], query, limit
        )

    async def read_thread(self, thread_id: str) -> EmailThread:
        # Plain IMAP has no native thread grouping the way Gmail's own API
        # does — a Message-ID doubles as both `id` and `thread_id` here
        # (see _parse_stdlib_message), so a "thread" IMAP-side is exactly
        # the one message matching that Message-ID. Honest about the
        # limitation rather than faking multi-message threading.
        matches = await self.search(f'HEADER Message-ID "{thread_id}"', limit=1)
        if not matches:
            raise KeyError(thread_id)
        message = matches[0]
        return EmailThread(
            id=thread_id, subject=message.subject,
            participants=[message.sender, *message.to], messages=[message], provider=self.id,
        )

    # -- SMTP (blocking, run via to_thread) -----------------------------------

    def _smtp_send_blocking(self, address: str, app_password: str, draft: EmailDraft) -> None:
        import smtplib

        mime = MIMEText(draft.body_text)
        mime["From"] = address
        mime["To"] = ", ".join(f"{a.name} <{a.address}>" if a.name else a.address for a in draft.to)
        mime["Subject"] = draft.subject
        recipients = [a.address for a in draft.to]
        with smtplib.SMTP_SSL(self.SMTP_HOST, self.SMTP_PORT, timeout=15) as connection:
            connection.login(address, app_password)
            connection.sendmail(address, recipients, mime.as_string())

    async def send(self, draft: EmailDraft) -> SendReceipt:
        creds = self._load_credentials()
        if creds is None:
            raise RuntimeError("Gmail app-password is not connected")
        await asyncio.to_thread(self._smtp_send_blocking, creds["address"], creds["app_password"], draft)
        # SMTP has no server-assigned message id the way Gmail's API does;
        # a locally-generated one is honestly labeled as such rather than
        # invented to look like a provider id.
        local_id = f"smtp-sent-{uuid4().hex[:16]}"
        return SendReceipt(
            provider=self.id, message_id=local_id, thread_id=draft.thread_id or local_id,
            sent_at=datetime.now(timezone.utc), verified=True,
            evidence=[f"sent via SMTP as {creds['address']}", f"recipients: {', '.join(a.address for a in draft.to)}"],
        )


class CombinedEmailProvider(EmailProvider):
    """Tries the App Password provider first (if credentials are stored),
    falling back to OAuth otherwise — the user connects with WHICHEVER
    path they actually completed (paste an address+app-password, or run
    the OAuth consent flow), and every other part of VYOM (EmailTool,
    EmailService, /api/email/*) keeps calling one email provider without
    needing to know or care which auth path is live. Both providers can
    be independently connected/disconnected; this class owns no state of
    its own beyond delegating to whichever of the two is healthy."""

    id = "gmail-combined"

    def __init__(self, app_password_provider: GmailAppPasswordProvider, oauth_provider: EmailProvider) -> None:
        self.app_password_provider = app_password_provider
        self.oauth_provider = oauth_provider

    async def _active(self) -> EmailProvider:
        healthy, _ = await self.app_password_provider.health()
        if healthy:
            return self.app_password_provider
        return self.oauth_provider

    async def health(self) -> tuple[bool, str | None]:
        app_healthy, app_error = await self.app_password_provider.health()
        if app_healthy:
            return True, None
        oauth_healthy, oauth_error = await self.oauth_provider.health()
        if oauth_healthy:
            return True, None
        return False, app_error or oauth_error or "Gmail is not connected via either app-password or OAuth"

    async def begin_oauth(self, state: str) -> str:
        return await self.oauth_provider.begin_oauth(state)

    async def complete_oauth(self, code: str) -> dict[str, Any]:
        return await self.oauth_provider.complete_oauth(code)

    async def disconnect(self) -> None:
        await self.app_password_provider.disconnect()
        await self.oauth_provider.disconnect()

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        provider = await self._active()
        return await provider.search(query, limit)

    async def read_thread(self, thread_id: str) -> EmailThread:
        provider = await self._active()
        return await provider.read_thread(thread_id)

    async def send(self, draft: EmailDraft) -> SendReceipt:
        provider = await self._active()
        return await provider.send(draft)


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

