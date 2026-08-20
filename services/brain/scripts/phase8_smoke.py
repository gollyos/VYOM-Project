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
    with tempfile.TemporaryDirectory(prefix="vyom-phase8-api-", ignore_cleanup_errors=True) as root:
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

            # Deep research
            research_task = client.post("/api/tasks", json={"user_request": "Research the top competitors for our SaaS and tell me where we can win"}).json()
            research_task = wait_for(client, research_task["id"], {"completed", "failed"})
            assert research_task["status"] == "completed", research_task
            assert research_task["assigned_model"] == "local-phase8-runtime-v1"
            assert research_task["result"]["ui_composition"]["objects"]
            assert any(obj["type"] == "research-map" for obj in research_task["result"]["ui_composition"]["objects"])
            print("research: OK, sources=", len(research_task["result"]["structured_data"]["sources"]))

            # Tool discovery
            tool_task = client.post("/api/tasks", json={"user_request": "Find a cheap tool/API that can transcribe our meetings"}).json()
            tool_task = wait_for(client, tool_task["id"], {"completed", "failed"})
            assert tool_task["status"] == "completed", tool_task
            print("tool_discovery: OK ->", tool_task["result"]["response"][:80])

            # MCP discovery
            mcp_task = client.post("/api/tasks", json={"user_request": "Can VYOM connect to GitHub issues?"}).json()
            mcp_task = wait_for(client, mcp_task["id"], {"completed", "failed"})
            assert mcp_task["status"] == "completed", mcp_task
            print("mcp_discovery: OK ->", mcp_task["result"]["response"][:80])

            # Booking search (disconnected by default -> honest unavailable, not fake data)
            booking_task = client.post("/api/tasks", json={"user_request": "Find me a good restaurant near tomorrow's client meeting for 4 people around 7 PM"}).json()
            booking_task = wait_for(client, booking_task["id"], {"completed", "failed"})
            assert booking_task["status"] == "completed", booking_task
            assert booking_task["result"]["structured_data"].get("available") is False
            print("booking_search: OK (honestly unavailable, no fake reservation)")

            # Client report artifact
            report_task = client.post("/api/tasks", json={"user_request": "Create this week's client report for Finora"}).json()
            report_task = wait_for(client, report_task["id"], {"completed", "failed"})
            assert report_task["status"] == "completed", report_task
            artifact_id = report_task["result"]["structured_data"]["id"]
            artifact = client.get(f"/api/artifacts/{artifact_id}").json()
            assert artifact["status"] == "validated"
            assert Path(artifact["output_path"]).exists()
            print("client_report: OK, artifact validated at", artifact["output_path"])

            # Presentation
            presentation_task = client.post("/api/tasks", json={"user_request": "Turn the competitor research into a client presentation about VYOM pricing"}).json()
            presentation_task = wait_for(client, presentation_task["id"], {"completed", "failed"})
            assert presentation_task["status"] == "completed", presentation_task
            print("presentation: OK ->", presentation_task["result"]["response"][:80])

            # Client delivery preparation (never auto-sends)
            delivery_task = client.post("/api/tasks", json={"user_request": "Prepare everything ready to send to Finora"}).json()
            delivery_task = wait_for(client, delivery_task["id"], {"completed", "needs_approval", "failed"})
            assert delivery_task["status"] in {"completed", "needs_approval"}, delivery_task
            print("client_delivery: OK, status =", delivery_task["status"])

            print("PHASE 8 API SMOKE PASSED: research, tool discovery, MCP discovery, honest booking unavailability, client report artifact, presentation, delivery package prep")


if __name__ == "__main__":
    main()
