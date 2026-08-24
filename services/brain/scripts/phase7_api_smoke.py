from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def wait_for(client: TestClient, task_id: str, terminal: set[str], timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in terminal:
            return task
        time.sleep(0.03)
    raise RuntimeError(f"Task {task_id} did not reach {terminal}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vyom-phase7-api-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db",
            skills_root=base / "skills",
            agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl",
            secret_store_path=base / "secrets",
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").json()["status"] == "ok"
            integrations = client.get("/api/integrations").json()
            assert integrations and all(item["status"] == "disconnected" for item in integrations)

            status_task = client.post("/api/tasks", json={"user_request": "What is my status today?"}).json()
            status_task = wait_for(client, status_task["id"], {"completed", "failed"})
            assert status_task["status"] == "completed"
            assert status_task["result"]["structured_data"]["incomplete"] is True
            assert status_task["assigned_model"] == "workflow:business-v1"

            agency_task = client.post("/api/tasks", json={"user_request": "Show agency"}).json()
            agency_task = wait_for(client, agency_task["id"], {"completed", "failed"})
            assert agency_task["status"] == "completed"
            assert agency_task["result"]["structured_data"]["counts"]["qualified"] == 0

            approval_task = client.post("/api/tasks", json={"user_request": "Schedule meeting: Client review"}).json()
            approval_task = wait_for(client, approval_task["id"], {"needs_approval", "failed"})
            assert approval_task["status"] == "needs_approval"
            pending = client.get("/api/approvals").json()
            assert any(item["task_id"] == approval_task["id"] for item in pending)
            rejected = client.post(f"/api/approvals/{approval_task['id']}", json={"approved": False}).json()
            assert rejected["status"] == "cancelled"

            print("PHASE 7 API SMOKE PASSED: health, disconnected registry, real partial briefing, CRM agency view, scoped approval/rejection")


if __name__ == "__main__":
    main()
