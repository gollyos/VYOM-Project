#!/usr/bin/env python3
"""VYOM smoke-test — golden end-to-end flows proving Phases 1-13 still
integrate, against a real in-process Brain (offline, no paid APIs):

  G1 project inspection + build memory (real filesystem tools)
  G2 "What is my status today?" (real source-aware briefing)
  G3 client report artifact (real render + validation)
  G4 durable automation (real scheduled execution)
  G5 distributed mock (mobile command -> task -> audit)
  G6 alpha onboarding (first run -> complete -> restart -> no re-run)

Usage: python scripts/smoke-test.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "services" / "brain"
sys.path.insert(0, str(BRAIN))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.devices.schemas import utc_now  # noqa: E402
from app.main import create_app  # noqa: E402


def wait_for(client: TestClient, task_id: str, terminal: set[str], timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in terminal:
            return task
        time.sleep(0.05)
    raise RuntimeError(f"task {task_id} did not reach {terminal} (last: {task['status']})")


def run_task(client: TestClient, command: str, timeout: float = 60) -> dict:
    created = client.post("/api/tasks", json={"user_request": command}).json()
    return wait_for(client, created["id"], {"completed", "failed", "needs_approval"}, timeout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vyom-smoke-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").json()["status"] == "ok"

            # G1 — real filesystem inspection + persistent build memory.
            inspect = run_task(client, "Inspect this project and remember how it is built", timeout=120)
            assert inspect["status"] == "completed", inspect.get("error")
            recall = run_task(client, "How do I build this project?")
            assert recall["status"] == "completed", recall.get("error")
            print(f"G1 project inspection + build memory: OK ({inspect['assigned_model']})")

            # G2 — real source-aware briefing.
            status = run_task(client, "What is my status today?")
            assert status["status"] == "completed"
            print("G2 daily status briefing: OK")

            # G3 — real artifact render + validation.
            report = run_task(client, "Create a client report for Finora", timeout=120)
            assert report["status"] in ("completed", "needs_approval"), report.get("error")
            print(f"G3 client report artifact: OK ({report['status']})")

            # G4 — durable automation scheduled into the past runs once.
            created = client.post("/api/automations", json={
                "name": "smoke-briefing", "type": "one_time",
                "run_at": (utc_now() - timedelta(seconds=1)).isoformat(),
                "action": "prepare_agency_briefing",
            })
            assert created.status_code in (200, 201), created.text
            deadline = time.monotonic() + 20
            ran = False
            while time.monotonic() < deadline:
                definitions = client.get("/api/automations").json()
                definition = next((a for a in definitions if a["name"] == "smoke-briefing"), None)
                if definition and (definition.get("run_count") or 0) >= 1:
                    ran = True
                    break
                time.sleep(0.2)
            assert ran, "automation never ran"
            print("G4 durable automation: OK (ran without a desktop UI)")

            # G5 — distributed mock: pair a phone properly, then command -> task -> audit.
            pairing = client.post("/api/devices/pair", json={
                "name": "Smoke Phone", "device_type": "mobile", "platform": "android",
                "requested_capabilities": ["notifications.send"],
            }).json()
            approved = client.post(f"/api/devices/pair/{pairing['request_id']}/approve", json={
                "allowed_capabilities": ["notifications.send"],
            }).json()
            node_id = approved["node"]["node_id"]
            client.post(f"/api/nodes/{node_id}/heartbeat", json={"presence": {}})
            session = client.post("/api/remote/session", json={
                "node_id": node_id, "token": approved["token"],
            }).json()
            envelope = {
                "command": "What is my status today?", "source_node": node_id,
                "session_id": session["session_id"],
                "command_id": "rcmd_smoke_1", "nonce": "nonce_smoke_1",
            }
            command = client.post("/api/remote/command", json=envelope).json()
            assert command.get("accepted") is True, command
            replay = client.post("/api/remote/command", json=envelope)
            assert replay.status_code == 409
            summary = client.get("/api/remote/away-summary", params={
                "since_iso": (utc_now() - timedelta(hours=1)).isoformat(),
            }).json()
            assert summary["node_actions"], "distributed audit empty"
            print("G5 distributed mock + replay rejection + audit: OK")

        # G6 — onboarding completes once and never reappears after restart.
        with TestClient(create_app(settings)) as client2:
            setup = client2.get("/api/setup/status").json()
            assert setup["needs_onboarding"] is True
            order = ["intro", "preferences", "voice_test", "microphone", "privacy", "provider",
                     "workspace", "integrations", "autonomy", "notifications", "startup", "diagnostics", "ready"]
            for step_id in order:
                payload = {}
                if step_id == "privacy":
                    payload = {"choices": {"external_models": "ask", "personal_memory": "enabled"}}
                if step_id == "autonomy":
                    payload = {"preset": "balanced"}
                response = client2.post(f"/api/setup/steps/{step_id}/complete", json={"data": payload})
                assert response.status_code == 200, response.text
            final = client2.get("/api/setup/status").json()
            assert final["finished"] is True and final["needs_onboarding"] is False

        with TestClient(create_app(settings)) as client3:
            restarted = client3.get("/api/setup/status").json()
            assert restarted["needs_onboarding"] is False, "onboarding reappeared after restart"
            print("G6 alpha onboarding (complete once, no re-run after restart): OK")

    print("\nsmoke-test: ALL GOLDEN FLOWS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
