from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def wait_for(client: TestClient, task_id: str, terminal: set[str], timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in terminal:
            return task
        time.sleep(0.03)
    raise RuntimeError(f"Task {task_id} did not reach {terminal}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vyom-phase9-api-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db",
            skills_root=base / "skills",
            agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl",
            secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts",
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").json()["status"] == "ok"

            # System status ("why is my PC slow?") -- L0 read-only, safe metrics only.
            status_task = client.post("/api/tasks", json={"user_request": "Why is my PC slow?"}).json()
            status_task = wait_for(client, status_task["id"], {"completed", "failed"})
            assert status_task["status"] == "completed", status_task
            assert status_task["assigned_model"] == "workflow:desktop-v1"
            print("system_status_explain: OK ->", status_task["result"]["response"][:80])

            # Startup status -- read only, no OS mutation.
            startup_task = client.post("/api/tasks", json={"user_request": "Check startup status"}).json()
            startup_task = wait_for(client, startup_task["id"], {"completed", "failed"})
            assert startup_task["status"] == "completed", startup_task
            assert startup_task["result"]["structured_data"]["enabled"] is False
            print("desktop_startup_status: OK (disabled by default)")

            # Screen context ("what am I looking at?") -- real capture + observation.
            context_task = client.post("/api/tasks", json={"user_request": "What am I looking at?"}).json()
            context_task = wait_for(client, context_task["id"], {"completed", "failed"})
            assert context_task["status"] == "completed", context_task
            print("screen_context: OK ->", context_task["result"]["response"][:80])

            # Window arrangement -- native window API, no mouse dragging.
            window_task = client.post("/api/tasks", json={"user_request": "Put the editor on the left and browser on the right"}).json()
            window_task = wait_for(client, window_task["id"], {"completed", "failed"})
            assert window_task["status"] == "completed", window_task
            print("window_arrangement: OK ->", window_task["result"]["response"][:80])

            # Contextual save with empty clipboard -- honest "no context" result.
            client.post("/api/desktop/emergency-pause")  # exercise the endpoint path
            client.post("/api/desktop/emergency-resume")
            save_task = client.post("/api/tasks", json={"user_request": "Save a copy of this in my VYOM project"}).json()
            save_task = wait_for(client, save_task["id"], {"completed", "failed"})
            assert save_task["status"] == "completed", save_task
            print("contextual_save: OK ->", save_task["result"]["response"][:80])

            # Device node: pair -> approve -> heartbeat -> list -> revoke.
            pair_response = client.post("/api/devices/pair", json={
                "name": "Test Laptop", "device_type": "laptop", "platform": "windows",
                "requested_capabilities": ["notifications.send", "app.open"],
            }).json()
            approve_response = client.post(f"/api/devices/pair/{pair_response['request_id']}/approve", json={
                "allowed_capabilities": ["notifications.send", "app.open"],
            }).json()
            node_id = approve_response["node"]["node_id"]
            client.post(f"/api/devices/{node_id}/heartbeat")
            devices = client.get("/api/devices").json()
            assert any(device["node_id"] == node_id and device["online"] == "online" for device in devices)
            client.post(f"/api/devices/{node_id}/revoke")
            devices_after = client.get("/api/devices").json()
            assert any(device["node_id"] == node_id and device["trust_level"] == "revoked" for device in devices_after)
            print("device_pairing: OK (paired, heartbeat online, revoked)")

            # Displays endpoint (multi-monitor foundation).
            displays = client.get("/api/screen/displays").json()
            print("displays: OK ->", len(displays), "display(s)")

            print("PHASE 9 API SMOKE PASSED: system status, startup status, screen context, window arrangement, contextual save, device pairing lifecycle, displays")


if __name__ == "__main__":
    main()
