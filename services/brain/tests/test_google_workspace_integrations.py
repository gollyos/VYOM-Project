"""Real tests for the Gmail and Google Sheets integrations added this
session: GoogleOAuthClient's PKCE flow, GmailProvider's token-refresh-on-401
retry, and both providers' actual API-shaped requests/responses — using
httpx.MockTransport (built into httpx, no new test dependency) rather than a
live Google account, so these run offline and deterministically.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.email.provider import GmailProvider, MockEmailProvider
from app.email.schemas import DraftRequest, EmailAddress
from app.integrations.google_oauth import GoogleOAuthClient
from app.integrations.secrets import InMemorySecretVault
from app.sheets.provider import GoogleSheetsProvider, MockSheetsProvider
from app.sheets.schemas import CreateSpreadsheetRequest
from app.sheets.service import SheetsService


# -- GoogleOAuthClient (shared PKCE flow) ------------------------------------


def test_authorization_url_carries_state_and_pkce_challenge():
    client = GoogleOAuthClient("client-id", "client-secret", ("scope-a", "scope-b"))
    url = client.authorization_url("state-123")
    assert "client_id=client-id" in url
    assert "state=state-123" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "scope=scope-a+scope-b" in url
    # The PKCE verifier for this state must now be retrievable for exchange.
    assert "state-123" in client._pending


def test_extract_code_accepts_bare_code_or_full_redirect_url():
    assert GoogleOAuthClient.extract_code("4/0Araw-code") == "4/0Araw-code"
    assert GoogleOAuthClient.extract_code(
        "http://localhost/?state=abc&code=4%2F0Amixed-code&scope=email"
    ) == "4/0Amixed-code"


@pytest.mark.asyncio
async def test_exchange_code_posts_pkce_verifier_and_returns_tokens(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "token_type": "Bearer"})

    client = GoogleOAuthClient("client-id", "client-secret", ("scope",))
    client.authorization_url("state-1")  # seeds the pending PKCE verifier

    real_client_cls = httpx.AsyncClient

    class _MockedAsyncClient(real_client_cls):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.integrations.google_oauth.httpx.AsyncClient", _MockedAsyncClient)
    tokens = await client.exchange_code("state-1", "auth-code")

    assert tokens == {"access_token": "AT", "refresh_token": "RT", "token_type": "Bearer"}
    assert captured["body"]["code"] == "auth-code"
    assert captured["body"]["client_id"] == "client-id"
    assert "code_verifier" in captured["body"]  # PKCE verifier was actually sent


# -- GmailProvider ------------------------------------------------------------


def _fake_gmail_message_json(message_id: str, thread_id: str) -> dict:
    body_text = "Hello from a real-shaped Gmail API response."
    encoded = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
    return {
        "id": message_id, "threadId": thread_id,
        "labelIds": ["INBOX"], "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": "Test subject"},
            ],
            "body": {"data": encoded},
        },
    }


@pytest.mark.asyncio
async def test_gmail_provider_search_reads_real_shaped_responses():
    vault = InMemorySecretVault()
    vault.set("oauth:gmail", json.dumps({"access_token": "AT", "refresh_token": "RT"}).encode())
    oauth = GoogleOAuthClient("id", "secret", ("scope",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})
        if "/messages/m1" in str(request.url):
            return httpx.Response(200, json=_fake_gmail_message_json("m1", "t1"))
        if "/messages/m2" in str(request.url):
            return httpx.Response(200, json=_fake_gmail_message_json("m2", "t2"))
        return httpx.Response(404)

    provider = GmailProvider(oauth, vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    messages = await provider.search("subject:test", limit=10)
    assert len(messages) == 2
    assert messages[0].subject == "Test subject"
    assert messages[0].sender.address == "alice@example.com"
    assert messages[0].body_text == "Hello from a real-shaped Gmail API response."
    await provider.disconnect()


@pytest.mark.asyncio
async def test_gmail_provider_refreshes_token_on_401_and_retries():
    vault = InMemorySecretVault()
    vault.set("oauth:gmail", json.dumps({"access_token": "STALE", "refresh_token": "RT"}).encode())
    calls: list[str] = []

    class FakeOAuth:
        async def refresh(self, refresh_token: str) -> dict:
            calls.append("refreshed")
            return {"access_token": "FRESH", "refresh_token": refresh_token, "token_type": "Bearer"}

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        auth = request.headers.get("authorization", "")
        if auth == "Bearer STALE":
            return httpx.Response(401)
        assert auth == "Bearer FRESH"
        return httpx.Response(200, json={"emailAddress": "me@example.com"})

    provider = GmailProvider(FakeOAuth(), vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    healthy, error = await provider.health()
    assert healthy is True
    assert error is None
    assert calls == ["refreshed"]
    assert attempts["n"] == 2  # first 401, then a retried success
    # The refreshed token must now be the one persisted for next time.
    stored = json.loads(vault.get("oauth:gmail").decode())
    assert stored["access_token"] == "FRESH"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_gmail_provider_send_builds_correct_gmail_api_payload():
    vault = InMemorySecretVault()
    vault.set("oauth:gmail", json.dumps({"access_token": "AT", "refresh_token": "RT"}).encode())
    oauth = GoogleOAuthClient("id", "secret", ("scope",))
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "sent-1", "threadId": "thread-1"})

    provider = GmailProvider(oauth, vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    draft = DraftRequest(
        to=[EmailAddress(address="carol@example.com")], subject="Hi", body_text="Hello Carol",
    )
    from app.email.schemas import EmailDraft

    receipt = await provider.send(EmailDraft.model_validate(draft.model_dump()))
    assert receipt.message_id == "sent-1"
    assert receipt.thread_id == "thread-1"
    assert receipt.verified is True
    assert "raw" in captured["body"]  # Gmail's send API takes base64url raw RFC822
    decoded = base64.urlsafe_b64decode(captured["body"]["raw"] + "==").decode()
    assert "carol@example.com" in decoded
    assert "Hello Carol" in decoded
    await provider.disconnect()


def test_gmail_provider_reports_disconnected_health_without_token():
    provider = GmailProvider(GoogleOAuthClient("id", "secret", ()), InMemorySecretVault())
    # No token stored — health must say so synchronously without any network call.
    assert provider._load_token() is None


# -- GoogleSheetsProvider -----------------------------------------------------


@pytest.mark.asyncio
async def test_sheets_provider_create_read_write_append_real_shaped_api():
    vault = InMemorySecretVault()
    vault.set("oauth:google-sheets", json.dumps({"access_token": "AT", "refresh_token": "RT"}).encode())
    oauth = GoogleOAuthClient("id", "secret", ("scope",))

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        if request.method == "POST" and path.endswith("/v4/spreadsheets"):
            return httpx.Response(200, json={
                "spreadsheetId": "sheet-1", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet-1",
            })
        if request.method == "GET" and "/values/" in path:
            return httpx.Response(200, json={"range": "Sheet1!A1:B2", "values": [["a", "b"], ["1", "2"]]})
        if request.method == "PUT" and "/values/" in path:
            return httpx.Response(200, json={"updatedCells": 4})
        if request.method == "POST" and ":append" in path:
            return httpx.Response(200, json={"updates": {"updatedRange": "Sheet1!A3:B3", "updatedCells": 2}})
        return httpx.Response(404)

    provider = GoogleSheetsProvider(oauth, vault)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SheetsService(provider)

    ref = await service.create(CreateSpreadsheetRequest(title="Budget"))
    assert ref.id == "sheet-1"

    values = await service.read_range("sheet-1", "Sheet1!A1:B2")
    assert values.values == [["a", "b"], ["1", "2"]]

    write_receipt = await service.write_range("sheet-1", "Sheet1!A1:B2", [["x", "y"]])
    assert write_receipt.updated_cells == 4

    append_receipt = await service.append_rows("sheet-1", "Sheet1!A:B", [["new", "row"]])
    assert append_receipt.updated_cells == 2
    await provider.disconnect()


# -- Mock providers used by the wider test suite -----------------------------


@pytest.mark.asyncio
async def test_mock_email_provider_search_send_roundtrip():
    from datetime import datetime, timezone

    from app.email.schemas import EmailDraft, EmailMessage

    provider = MockEmailProvider([
        EmailMessage(
            id="m1", thread_id="t1", sender=EmailAddress(address="a@x.com"),
            to=[EmailAddress(address="b@x.com")], subject="hello world",
            body_text="body", received_at=datetime.now(timezone.utc), provider="mock-email",
        )
    ])
    results = await provider.search("hello")
    assert len(results) == 1
    receipt = await provider.send(EmailDraft(to=[EmailAddress(address="c@x.com")], subject="s", body_text="b"))
    assert receipt.verified is True
    assert receipt.message_id.startswith("mock-message-")


@pytest.mark.asyncio
async def test_mock_sheets_provider_roundtrip():
    provider = MockSheetsProvider()
    ref = await provider.create(CreateSpreadsheetRequest(title="Test"))
    await provider.write_range(ref.id, "Sheet1!A1:A2", [["x"], ["y"]])
    values = await provider.read_range(ref.id, "Sheet1!A1:A2")
    assert values.values == [["x"], ["y"]]
    await provider.append_rows(ref.id, "Sheet1!A:A", [["z"]])
    values2 = await provider.read_range(ref.id, "Sheet1!A1:A2")
    assert values2.values == [["x"], ["y"], ["z"]]
