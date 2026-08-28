import hashlib
import hmac
import pytest
from app.automation.webhook_engine import WebhookEngine, WebhookEvent


@pytest.mark.asyncio
async def test_webhook_engine_signature_and_deduplication():
    received_events: list[WebhookEvent] = []

    async def on_event(ev: WebhookEvent):
        received_events.append(ev)

    engine = WebhookEngine(dispatch_handler=on_event)
    secret = "super_secret_webhook_key_123"
    engine.set_webhook_secret("github", secret)

    raw_body = b'{"action": "opened", "issue": {"number": 42, "title": "Critical Bug"}}'
    sig_256 = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # 1. Valid Signature
    res = await engine.ingest_event(
        connector_id="github",
        event_type="issues",
        payload={"action": "opened"},
        raw_body=raw_body,
        headers={"X-GitHub-Delivery": "delivery_001", "X-Hub-Signature-256": f"sha256={sig_256}"},
    )
    assert res["status"] == "accepted"
    assert res["verified"] is True
    assert len(received_events) == 1

    # 2. Duplicate Event Delivery (Replay Protection)
    res_dup = await engine.ingest_event(
        connector_id="github",
        event_type="issues",
        payload={"action": "opened"},
        raw_body=raw_body,
        headers={"X-GitHub-Delivery": "delivery_001", "X-Hub-Signature-256": f"sha256={sig_256}"},
    )
    assert res_dup["status"] == "ignored"
    assert res_dup["reason"] == "duplicate"
    assert len(received_events) == 1  # Not dispatched twice

    # 3. Invalid Signature Tampering
    res_invalid = await engine.ingest_event(
        connector_id="github",
        event_type="issues",
        payload={"action": "opened"},
        raw_body=b'{"tampered": true}',
        headers={"X-GitHub-Delivery": "delivery_002", "X-Hub-Signature-256": f"sha256={sig_256}"},
    )
    assert res_invalid["status"] == "rejected"
    assert res_invalid["reason"] == "invalid_signature"
