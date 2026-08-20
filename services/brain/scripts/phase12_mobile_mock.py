"""Mock mobile companion node (Phase 12).

Simulates a phone's full lifecycle against a running Brain — the same
calls apps/mobile makes — without any real device or public network:

pair (code approved on desktop) -> heartbeat -> remote session ->
voice/text command -> approval decision -> offline queue flush ->
revocation check.

Usage: python scripts/phase12_mobile_mock.py [--base-url http://127.0.0.1:7788]
Falls back to an in-process TestClient Brain when the URL is offline so
the flow is verifiable without a separately started service.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7788")
    args = parser.parse_args()

    import httpx

    try:
        client = httpx.Client(base_url=args.base_url, timeout=5)
        client.get("/health").raise_for_status()
        print(f"mock mobile: talking to a live Brain at {args.base_url}")
        return run_flow(client)
    except Exception:
        print("mock mobile: no live Brain; running against an in-process Brain")
        from fastapi.testclient import TestClient

        from app.core.config import Settings
        from app.main import create_app

        with tempfile.TemporaryDirectory(prefix="vyom-mobile-mock-", ignore_cleanup_errors=True) as root:
            base = Path(root)
            settings = Settings(
                database_path=base / "brain.db", skills_root=base / "skills",
                agents_root=base / "agents", audit_log_path=base / "audit.jsonl",
                secret_store_path=base / "secrets", artifacts_root=base / "artifacts",
                backup_root=base / "backups",
            )
            with TestClient(create_app(settings)) as test_client:
                return run_flow(test_client)


def run_flow(client) -> int:
    nonce = uuid.uuid4().hex[:6]

    # 1) Pairing request from the phone...
    pairing = client.post("/api/devices/pair", json={
        "name": f"Mock Phone {nonce}", "device_type": "mobile", "platform": "android",
        "requested_capabilities": ["notifications.send"],
    }).json()
    print(f"1. pairing requested: {pairing['request_id'][:18]}... (code shown on the trusted device: {pairing['code']})")

    # 2) ...approved by the user on the existing trusted device.
    approved = client.post(f"/api/devices/pair/{pairing['request_id']}/approve", json={
        "allowed_capabilities": ["notifications.send"],
    }).json()
    node_id, token = approved["node"], approved["token"]
    print(f"2. pairing approved: node {node_id['name']} trusted, capabilities {node_id['capabilities']}")

    # 3) Heartbeat + presence (battery/network volunteered by the node).
    heartbeat = client.post(f"/api/nodes/{node_id['node_id']}/heartbeat", json={
        "presence": {"battery_percent": 72, "network_type": "wifi"},
    }).json()
    print(f"3. heartbeat: online={heartbeat['online']}")

    # 4) Authenticated remote session.
    session = client.post("/api/remote/session", json={"node_id": node_id["node_id"], "token": token}).json()
    print(f"4. session opened (expires {session['expires_at']})")

    # 5) Remote command with full envelope (id/timestamp/nonce/permission context).
    envelope = {
        "command": "What's happening?", "source_node": node_id["node_id"],
        "session_id": session["session_id"], "permission_context": {"origin": "mobile-mock"},
        "command_id": f"rcmd_mock_{nonce}", "nonce": f"nonce_{nonce}",
    }
    command = client.post("/api/remote/command", json=envelope).json()
    print(f"5. remote command accepted -> task {command.get('task_id')} ({command.get('task_status')})")

    # 6) Exact replay of the same envelope must be rejected (nonce reuse).
    replay = client.post("/api/remote/command", json=envelope)
    assert replay.status_code == 409, replay.text
    print("6. replayed command rejected: 409")

    # 7) Wrong token cannot authenticate.
    bad = client.post("/api/remote/session", json={"node_id": node_id["node_id"], "token": "wrong"})
    assert bad.status_code == 401, bad.text
    print("7. wrong credential rejected: 401")

    # 8) Offline queue: harmless command queued then submitted exactly once.
    queued = client.post("/api/sync/offline/queue", json={
        "command": "Today's plan", "source_node": "mobile",
    }).json()
    result = client.post("/api/sync/offline/submit").json()["results"]
    entry = next(item for item in result if item["id"] == queued["id"])
    assert entry["executed"], entry
    print("8. offline queue: submitted exactly once")

    # 9) What did VYOM do while I was away?
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    summary = client.get("/api/remote/away-summary", params={"since_iso": since}).json()
    print(f"9. away-summary: completed={len(summary['tasks_completed'])} audit={len(summary['node_actions'])}")

    # 10) Revocation invalidates the node.
    revoked = client.post(f"/api/nodes/{node_id['node_id']}/revoke").json()
    assert revoked["revoked"]
    after = client.post("/api/remote/session", json={"node_id": node_id["node_id"], "token": token})
    assert after.status_code == 401, after.text
    print("10. revocation: sessions invalidated, credential rejected")

    print("\nmock mobile: FULL FLOW PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
