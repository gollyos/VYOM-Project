"""Tests for GmailAppPasswordProvider — the second, simpler Gmail connect
path added this session: paste an address + 16-char Google App Password,
no OAuth/Cloud-Console setup needed. Uses unittest.mock to patch stdlib
smtplib/imaplib rather than a real Gmail account, so these run offline
and deterministically.
"""
from __future__ import annotations

import email as email_stdlib
from unittest.mock import MagicMock, patch

import pytest

from app.email.provider import (
    CombinedEmailProvider,
    DisconnectedEmailProvider,
    GmailAppPasswordProvider,
)
from app.email.schemas import EmailAddress, EmailDraft
from app.integrations.secrets import InMemorySecretVault


def _valid_app_password() -> str:
    return "abcdefghijklmnop"  # 16 alnum chars, matches Google's real shape


def test_store_credentials_rejects_wrong_length_password():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    with pytest.raises(ValueError, match="16 characters"):
        provider.store_credentials("me@gmail.com", "tooshort")


def test_store_credentials_strips_cosmetic_spaces():
    # Google's own UI displays app passwords as "abcd efgh ijkl mnop" —
    # spaces are purely cosmetic and must be accepted, not rejected.
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", "abcd efgh ijkl mnop")
    creds = provider._load_credentials()
    assert creds["app_password"] == "abcdefghijklmnop"


def test_disconnect_removes_stored_credentials():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", _valid_app_password())
    assert provider._load_credentials() is not None
    import asyncio

    asyncio.run(provider.disconnect())
    assert provider._load_credentials() is None


@pytest.mark.asyncio
async def test_health_false_when_nothing_stored():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    healthy, error = await provider.health()
    assert healthy is False
    assert "not connected" in error


@pytest.mark.asyncio
async def test_health_true_when_imap_login_succeeds():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", _valid_app_password())

    mock_imap = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        healthy, error = await provider.health()

    assert healthy is True
    assert error is None
    mock_imap.login.assert_called_once_with("me@gmail.com", "abcdefghijklmnop")


@pytest.mark.asyncio
async def test_health_reports_friendly_error_on_bad_credentials():
    import imaplib

    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", _valid_app_password())

    mock_imap = MagicMock()
    mock_imap.login.side_effect = imaplib.IMAP4.error(
        "[AUTHENTICATIONFAILED] Invalid credentials (Failure)"
    )
    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        healthy, error = await provider.health()

    assert healthy is False
    assert "rejected" in error.lower()


@pytest.mark.asyncio
async def test_search_parses_real_shaped_imap_response():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", _valid_app_password())

    raw_message = email_stdlib.message_from_string(
        "From: Alice <alice@example.com>\r\n"
        "To: me@gmail.com\r\n"
        "Subject: Test subject\r\n"
        "Date: Mon, 25 Aug 2026 10:00:00 +0000\r\n"
        "Message-ID: <abc123@example.com>\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "Hello from IMAP."
    )
    raw_bytes = raw_message.as_bytes()

    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"1"])
    mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", raw_bytes)])
    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        messages = await provider.search("test", limit=10)

    assert len(messages) == 1
    assert messages[0].subject == "Test subject"
    assert messages[0].sender.address == "alice@example.com"
    assert messages[0].body_text.strip() == "Hello from IMAP."
    assert messages[0].provider == "gmail-app-password"


@pytest.mark.asyncio
async def test_send_builds_correct_smtp_call():
    provider = GmailAppPasswordProvider(InMemorySecretVault())
    provider.store_credentials("me@gmail.com", _valid_app_password())

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    with patch("smtplib.SMTP_SSL", return_value=mock_smtp):
        receipt = await provider.send(EmailDraft(
            to=[EmailAddress(address="bob@example.com")], subject="Hi", body_text="Hello Bob",
        ))

    assert receipt.verified is True
    assert receipt.provider == "gmail-app-password"
    mock_smtp.login.assert_called_once_with("me@gmail.com", "abcdefghijklmnop")
    args = mock_smtp.sendmail.call_args
    assert args[0][0] == "me@gmail.com"
    assert args[0][1] == ["bob@example.com"]
    assert "Hello Bob" in args[0][2]


@pytest.mark.asyncio
async def test_combined_provider_prefers_app_password_when_healthy():
    vault = InMemorySecretVault()
    app_password_provider = GmailAppPasswordProvider(vault)
    app_password_provider.store_credentials("me@gmail.com", _valid_app_password())
    oauth_provider = DisconnectedEmailProvider()
    combined = CombinedEmailProvider(app_password_provider, oauth_provider)

    mock_imap = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        healthy, error = await combined.health()

    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_combined_provider_falls_back_to_oauth_when_app_password_unset():
    from app.email.schemas import EmailMessage
    from datetime import datetime, timezone

    from app.email.provider import MockEmailProvider

    vault = InMemorySecretVault()
    app_password_provider = GmailAppPasswordProvider(vault)  # never connected
    oauth_provider = MockEmailProvider([
        EmailMessage(
            id="m1", thread_id="t1", sender=EmailAddress(address="a@x.com"),
            to=[EmailAddress(address="b@x.com")], subject="hi",
            body_text="body", received_at=datetime.now(timezone.utc), provider="mock-email",
        )
    ])
    combined = CombinedEmailProvider(app_password_provider, oauth_provider)

    healthy, error = await combined.health()
    assert healthy is True  # oauth (mock) is healthy even though app-password isn't

    results = await combined.search("hi")
    assert len(results) == 1  # delegated to the healthy oauth provider


@pytest.mark.asyncio
async def test_combined_provider_reports_disconnected_when_neither_works():
    vault = InMemorySecretVault()
    app_password_provider = GmailAppPasswordProvider(vault)
    oauth_provider = DisconnectedEmailProvider()
    combined = CombinedEmailProvider(app_password_provider, oauth_provider)

    healthy, error = await combined.health()
    assert healthy is False
    assert error is not None
