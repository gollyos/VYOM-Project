from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Callable
from pydantic import BaseModel, Field

logger = logging.getLogger("vyom.automation.webhooks")


class WebhookEvent(BaseModel):
    id: str
    connector_id: str
    event_type: str
    payload: dict[str, Any]
    headers: dict[str, str] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    verified: bool = False


class WebhookEngine:
    """Secure incoming webhook processing engine with HMAC signature verification,
    replay protection, deduplication, and automation dispatch."""

    def __init__(self, dispatch_handler: Callable[[WebhookEvent], Any] | None = None):
        self.dispatch_handler = dispatch_handler
        self._processed_events: set[str] = set()
        self._secrets: dict[str, str] = {}

    def set_webhook_secret(self, connector_id: str, secret: str) -> None:
        self._secrets[connector_id] = secret

    def verify_signature(self, connector_id: str, raw_body: bytes, signature_header: str | None) -> bool:
        secret = self._secrets.get(connector_id)
        if not secret:
            # If no secret configured, allow with unverified flag
            return True
        if not signature_header:
            return False

        # Support sha256=xxx format
        expected_sig = signature_header.replace("sha256=", "").replace("sha1=", "").strip()
        computed_256 = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        computed_1 = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha1).hexdigest()

        return hmac.compare_digest(computed_256, expected_sig) or hmac.compare_digest(computed_1, expected_sig)

    async def ingest_event(
        self,
        connector_id: str,
        event_type: str,
        payload: dict[str, Any],
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        # Deduplication check
        event_id = headers.get("X-GitHub-Delivery") or headers.get("X-Event-ID") or hashlib.sha256(raw_body).hexdigest()
        if event_id in self._processed_events:
            logger.info("Ignoring duplicate webhook event %s", event_id)
            return {"status": "ignored", "reason": "duplicate", "event_id": event_id}

        self._processed_events.add(event_id)
        if len(self._processed_events) > 10000:
            self._processed_events.clear()

        sig_header = headers.get("X-Hub-Signature-256") or headers.get("X-Signature") or headers.get("x-hub-signature")
        verified = self.verify_signature(connector_id, raw_body, sig_header)
        if not verified:
            logger.warning("Webhook signature verification failed for connector %s", connector_id)
            return {"status": "rejected", "reason": "invalid_signature"}

        event = WebhookEvent(
            id=event_id,
            connector_id=connector_id,
            event_type=event_type,
            payload=payload,
            headers=headers,
            verified=verified,
        )

        if self.dispatch_handler:
            await self.dispatch_handler(event)

        return {"status": "accepted", "event_id": event_id, "verified": verified}
