from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/{connector_id}")
async def receive_webhook(
    connector_id: str,
    request: Request,
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_event_type: str | None = Header(None, alias="X-Event-Type"),
) -> dict[str, Any]:
    webhook_engine = getattr(request.app.state, "webhook_engine", None)
    if not webhook_engine:
        raise HTTPException(status_code=503, detail="Webhook engine not initialized")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        payload = {"raw": raw_body.decode("utf-8", errors="ignore")}

    event_type = x_github_event or x_event_type or payload.get("event") or "generic_event"
    headers_dict = {k: v for k, v in request.headers.items()}

    res = await webhook_engine.ingest_event(
        connector_id=connector_id,
        event_type=event_type,
        payload=payload,
        raw_body=raw_body,
        headers=headers_dict,
    )
    if res.get("status") == "rejected":
        raise HTTPException(status_code=401, detail="Webhook signature verification failed")
    return res
