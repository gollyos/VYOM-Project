"""Tests for the WhatsApp connector added this session: a dedicated
services/brain/whatsapp_connector/connector.js Node child process
(real whatsapp-web.js + qrcode), wrapped by WhatsAppConnector so VYOM
has a first-class /api/whatsapp/{connect,status,send} surface instead
of only reaching WhatsApp through the generic MCP catalog. This gives
the QR code as a real base64 PNG data URL a UI can render directly,
which wweb-mcp's own REST/MCP surface does NOT expose (only to a
console/log).

These tests exercise WhatsAppConnector's event-parsing state machine
against a fake child process (no real Puppeteer/WhatsApp needed) — the
actual live QR generation was already verified manually against the
real connector.js + a real phone-scannable QR image this session.
"""
from __future__ import annotations

import json

import pytest

from app.whatsapp.connector import WhatsAppConnector, WhatsAppConnectorError
from app.whatsapp.schemas import WhatsAppStatus


def test_initial_status_is_disconnected(tmp_path):
    connector = WhatsAppConnector(connector_dir=tmp_path, auth_data_dir=tmp_path / "auth")
    assert connector.status.state == "disconnected"


def test_apply_event_qr_sets_qr_pending_with_data_url():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "qr", "data": "data:image/png;base64,ABC123"})
    assert connector.status.state == "qr_pending"
    assert connector.status.qr_data_url == "data:image/png;base64,ABC123"


def test_apply_event_ready_sets_ready_with_account_info():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "ready", "data": {"pushname": "Test User", "wid": "919876543210@c.us"}})
    assert connector.status.state == "ready"
    assert connector.status.pushname == "Test User"
    assert connector.status.wid == "919876543210@c.us"


def test_apply_event_disconnected_carries_reason():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "disconnected", "data": "LOGOUT"})
    assert connector.status.state == "disconnected"
    assert connector.status.detail == "LOGOUT"


def test_apply_event_auth_failure_is_surfaced_honestly():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "auth_failure", "data": "Session expired"})
    assert connector.status.state == "auth_failure"
    assert connector.status.detail == "Session expired"


@pytest.mark.asyncio
async def test_health_false_until_ready():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "qr", "data": "data:image/png;base64,X"})
    healthy, error = await connector.health()
    assert healthy is False
    assert "qr_pending" in error


@pytest.mark.asyncio
async def test_health_true_once_ready():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    connector._apply_event({"event": "ready", "data": {"pushname": "X", "wid": "1@c.us"}})
    healthy, error = await connector.health()
    assert healthy is True
    assert error is None


@pytest.mark.asyncio
async def test_start_raises_when_node_binary_missing(tmp_path):
    connector = WhatsAppConnector(
        connector_dir=tmp_path, auth_data_dir=tmp_path / "auth", node_bin="definitely-not-a-real-node-binary-xyz",
    )
    with pytest.raises(WhatsAppConnectorError, match="not found on PATH"):
        await connector.start()


@pytest.mark.asyncio
async def test_start_raises_when_connector_script_missing(tmp_path):
    # node_bin defaults to "node", which IS on PATH in this dev environment
    # (verified live this session) — so this exercises the "script not
    # found" branch specifically, not the "node missing" branch.
    connector = WhatsAppConnector(connector_dir=tmp_path, auth_data_dir=tmp_path / "auth")
    with pytest.raises(WhatsAppConnectorError, match="connector script not found"):
        await connector.start()


@pytest.mark.asyncio
async def test_send_message_before_connect_raises():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")
    with pytest.raises(WhatsAppConnectorError, match="not connected"):
        await connector.send_message("919876543210", "hello")


@pytest.mark.asyncio
async def test_send_recipient_gets_c_us_suffix_when_missing():
    """WhatsApp's internal addressing needs '@c.us' appended to a bare
    phone number — the caller shouldn't have to know that. Verified by
    inspecting what's actually written to the mocked child's stdin."""
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")

    written: list[bytes] = []

    class _FakeStdin:
        def write(self, data: bytes) -> None:
            written.append(data)

        async def drain(self) -> None:
            return None

    class _FakeProcess:
        returncode = None
        stdin = _FakeStdin()

    connector._process = _FakeProcess()
    await connector.send_message("919876543210", "hello")

    sent = json.loads(written[0].decode("utf-8").strip())
    assert sent["to"] == "919876543210@c.us"
    assert sent["body"] == "hello"


@pytest.mark.asyncio
async def test_send_recipient_keeps_existing_suffix():
    connector = WhatsAppConnector(connector_dir=".", auth_data_dir=".")

    written: list[bytes] = []

    class _FakeStdin:
        def write(self, data: bytes) -> None:
            written.append(data)

        async def drain(self) -> None:
            return None

    class _FakeProcess:
        returncode = None
        stdin = _FakeStdin()

    connector._process = _FakeProcess()
    await connector.send_message("919876543210@c.us", "hello")

    sent = json.loads(written[0].decode("utf-8").strip())
    assert sent["to"] == "919876543210@c.us"
