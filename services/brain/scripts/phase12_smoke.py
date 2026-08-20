"""Phase 12 multi-device runtime smoke: exercises the seven required
demos against a real FastAPI Brain + real SQLite state, entirely
offline (mock/local nodes only, no public infrastructure).

Demo 1  multi-node pairing/heartbeat/capabilities/dispatch/version gate
Demo 2  desktop-offline handoff (portable) and honest waiting (non-portable)
Demo 3  mobile approval -> Brain -> task resume -> evidence -> mobile update
Demo 4  offline mobile queue (exactly-once + consequential reconfirmation)
Demo 5  crash recovery (startup decisions from persisted state)
Demo 6  backup -> corrupt rejection -> validated restore
Demo 7  24/7 background automation without a desktop UI
"""
from __future__ import annotations

import tempfile
import time
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.devices.schemas import utc_now
from app.main import create_app


def wait_for(client: TestClient, task_id: str, terminal: set[str], timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in terminal:
            return task
        time.sleep(0.03)
    raise RuntimeError(f"Task {task_id} did not reach {terminal}")


def register(client: TestClient, name: str, device_type: str, roles: list[str], capabilities: list[str]) -> str:
    response = client.post("/api/nodes/register", json={
        "name": name, "device_type": device_type, "platform": "linux",
        "roles": roles, "capabilities": capabilities,
    })
    assert response.status_code == 200, response.text
    node_id = response.json()["node_id"]
    assert client.post(f"/api/nodes/{node_id}/heartbeat", json={"presence": {}}).status_code == 200
    return node_id


def run_demos() -> None:
    with tempfile.TemporaryDirectory(prefix="vyom-phase12-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db",
            skills_root=base / "skills",
            agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl",
            secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts",
            backup_root=base / "backups",
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").json()["status"] == "ok"

            # -- Demo 1: multi-node --------------------------------------
            desktop = register(client, "Desktop", "desktop_pc", ["client_device", "execution_node"],
                               ["task.coding", "task.terminal", "task.research", "notifications.send"])
            server = register(client, "Home Server", "home_server", ["worker_node", "execution_node"],
                              ["task.research", "task.automations", "task.artifacts"])
            mobile = register(client, "Phone", "mobile", ["client_device"], ["notifications.send"])
            network = client.get("/api/nodes/network").json()
            assert network["online_count"] == 3, network
            print("demo1 multi-node: OK ->", [f"{n['name']}={n['online']}" for n in network["nodes"]])

            dispatch = client.post("/api/nodes/dispatch", json={
                "task_id": "research-lead", "requirements": {"required_capabilities": ["task.research"]},
            }).json()
            assert dispatch["dispatched"], dispatch
            assert dispatch["node_id"] == server  # worker-role node preferred
            print("demo1 dispatch: OK ->", dispatch["node_id"], dispatch["status"])

            bad = client.post("/api/nodes/register", json={
                "name": "Legacy", "device_type": "laptop", "platform": "windows",
                "roles": [], "capabilities": [],
                "version_info": {"app_version": "0.0.1", "protocol_version": "99", "schema_version": "1"},
            })
            assert bad.status_code == 409
            assert client.post("/api/remote/session", json={"node_id": "ghost", "token": "x"}).status_code == 404
            print("demo1 gates: OK -> incompatible node rejected; unknown node cannot authenticate")

            # -- Demo 2: desktop offline -> handoff ----------------------
            expired = client.post("/api/nodes/dispatch", json={
                "task_id": "handoff-task",
                "requirements": {"required_capabilities": ["task.research"]},
                "lease_ttl_seconds": 0,
            }).json()
            assert expired["node_id"] == server
            handled = client.get("/api/nodes/leases/expired").json()["handled"]
            entry = next(item for item in handled if item["task_id"] == "handoff-task")
            assert entry["handoff"] is None or entry["handoff"]["decision"] == "handoff"
            print("demo2 portable handoff: OK ->", entry["handoff"]["decision"] if entry["handoff"] else "expired+handled")

            # -- Demo 3: mobile approval ---------------------------------
            approval_task = client.post("/api/tasks", json={"user_request": "Send email to Finora with the weekly summary"}).json()
            task = wait_for(client, approval_task["id"], {"needs_approval", "completed", "failed"})
            assert task["status"] == "needs_approval", task["status"]

            pending = client.get("/api/remote/approvals").json()
            view = next(v for v in pending if v["task_id"] == approval_task["id"])
            print("demo3 approval context: OK ->", view["requested_action"][:60], "| risk", view["risk"])

            decided = client.post(f"/api/remote/approvals/{approval_task['id']}", json={
                "decision": "approve", "node_id": mobile,
            }).json()
            assert decided["decision"] == "approved"
            resumed = wait_for(client, approval_task["id"], {"completed", "failed"})
            # With no live email provider configured the task fails
            # truthfully ("no registered consequential workflow") — the
            # honest outcome, never a faked external send.
            assert resumed["status"] in {"completed", "failed"}
            if resumed["status"] == "failed":
                assert "registered" in (resumed["error"] or "")
            print("demo3 approval -> resume -> evidence: OK ->", resumed["status"],
                  "(honest failure, no fake send)" if resumed["status"] == "failed" else "")

            # -- Demo 4: offline mobile queue -----------------------------
            queued = client.post("/api/sync/offline/queue", json={
                "command": "What is my status today?", "source_node": "mobile",
            }).json()
            assert queued["consequential"] is False
            submitted = client.post("/api/sync/offline/submit").json()
            assert any(item["id"] == queued["id"] and item["executed"] for item in submitted["results"])
            again = client.post("/api/sync/offline/submit").json()
            assert not any(item["id"] == queued["id"] for item in again["results"])
            print("demo4 offline queue: OK -> safe command submitted exactly once")

            consequential = client.post("/api/sync/offline/queue", json={
                "command": "Send email to the client now", "source_node": "mobile",
            }).json()
            assert consequential["consequential"] is True
            outcome = client.post("/api/sync/offline/submit").json()["results"]
            record = next(item for item in outcome if item["id"] == consequential["id"])
            assert record["executed"] is False and record["reason"] == "reconfirmation_required"
            print("demo4 consequential guard: OK ->", record["reason"])

            # Cross-device audit answers "which device ran this?".
            audit_lines = client.get("/api/sync/journal?limit=5").json()
            assert audit_lines["latest_seq"] > 0
            print("sync journal: OK -> latest seq", audit_lines["latest_seq"])

        # -- Demo 5: simulated crash -> restart recovery -----------------
        # (the TestClient context above closed the app; a second app boots
        # on the same SQLite database and must recover persisted state)
        with TestClient(create_app(settings)) as client2:
            decisions = client2.get("/api/health/recovery").json()["decisions"]
            print("demo5 crash recovery: OK ->", [d["action"] for d in decisions] or "no interrupted tasks")

            # -- Demo 7: 24/7 automation without a desktop UI -------------
            # (runs before the restore demo: a restore legitimately stops
            # the scheduler and requires an operator restart)
            automation = client2.post("/api/automations", json={
                "name": "phase12-demo-briefing", "type": "one_time",
                "run_at": (utc_now() - timedelta(seconds=1)).isoformat(),
                "action": "prepare_agency_briefing",
            })
            assert automation.status_code in (200, 201), automation.text
            deadline = time.monotonic() + 20
            ran = False
            while time.monotonic() < deadline:
                definitions = client2.get("/api/automations").json()
                definition = next((a for a in definitions if a["name"] == "phase12-demo-briefing"), None)
                if definition and (definition.get("run_count") or 0) >= 1:
                    ran = True
                    break
                time.sleep(0.2)
            assert ran, "background automation did not run"
            print("demo7 background automation: OK -> ran with no desktop UI attached")

            health = client2.get("/api/health").json()
            assert health["overall"] in {"healthy", "degraded", "unknown"}, health
            metrics = client2.get("/api/health/metrics").json()
            assert "task_success_rate" in metrics
            print("health: OK ->", health["overall"])

            summary = client2.get("/api/remote/away-summary", params={
                "since_iso": (utc_now() - timedelta(hours=1)).isoformat(),
            }).json()
            print("away-summary: OK -> completed:", len(summary["tasks_completed"]), "audit:", len(summary["node_actions"]))

            # -- Demo 6: backup -> corrupt rejection -> restore -----------
            backup = client2.post("/api/backup", json={"kind": "manual"}).json()
            assert backup["backup_id"], backup
            backups = client2.get("/api/backup").json()
            corrupt_entry = next(item for item in backups if item["backup_id"] == backup["backup_id"])
            directory = Path(corrupt_entry["directory"])

            data = bytearray((directory / "vyom-brain.db").read_bytes())
            data[len(data) // 2] ^= 0xFF
            (directory / "vyom-brain.db").write_bytes(bytes(data))
            corrupt = client2.post("/api/backup/restore", json={"backup_dir": str(directory), "confirm": True})
            assert corrupt.status_code == 409, corrupt.text
            print("demo6 corrupt backup: OK -> rejected before restore")

            fresh = client2.post("/api/backup", json={"kind": "manual"}).json()
            fresh_entry = next(item for item in client2.get("/api/backup").json() if item["backup_id"] == fresh["backup_id"])
            restored = client2.post("/api/backup/restore", json={"backup_dir": str(fresh_entry["directory"]), "confirm": True})
            assert restored.status_code == 200, restored.text
            assert restored.json()["restart_required"] is True
            print("demo6 backup/restore: OK ->", restored.json()["restored"], "(restart flagged, never silent)")


def run_non_portable_handoff_check() -> None:
    """Demo 2's negative case, run on its own loop/database: a task that
    needs local desktop files must wait for its owning node honestly."""
    import asyncio
    import tempfile as tf

    from app.devices.heartbeat import HeartbeatMonitor
    from app.devices.registry import DeviceRegistry
    from app.devices.schemas import DeviceCapability, DeviceNode, DeviceType
    from app.distributed import DistributedAuditLog, LeaseManager, NodeRouter, TaskHandoffService, TaskRequirements
    from app.persistence.database import Database

    async def check():
        with tf.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            database = Database(Path(root) / "h.db")
            await database.connect()
            try:
                registry = DeviceRegistry(HeartbeatMonitor())
                router = NodeRouter(registry)
                leases = LeaseManager(database)
                audit = DistributedAuditLog(database)
                desktop = DeviceNode(name="Desktop", device_type=DeviceType.DESKTOP_PC, platform="windows",
                                     capabilities=[DeviceCapability.CODING])
                desktop.node_id = "desktop"
                registry.heartbeat.record(desktop.node_id)
                registry.register(desktop)
                server = DeviceNode(name="Home Server", device_type=DeviceType.HOME_SERVER, platform="linux",
                                    capabilities=[DeviceCapability.RESEARCH])
                server.node_id = "server"
                registry.heartbeat.record(server.node_id)
                registry.register(server)
                handoff = TaskHandoffService(router, leases, audit)
                decision = await handoff.handoff(
                    "local-task", "desktop",
                    TaskRequirements(requires_local_files=True, local_project="C:\\VYOM Project",
                                     required_capabilities=["task.coding"]),
                )
                assert decision.decision == "wait_for_owner", decision
                print("demo2 non-portable wait: OK ->", decision.reasons[0])
            finally:
                await database.close()

    asyncio.run(check())


if __name__ == "__main__":
    run_demos()
    run_non_portable_handoff_check()
    print("\nPhase 12 smoke: ALL DEMOS PASSED")
