from __future__ import annotations

import asyncio
import json

import httpx
import websockets


BASE_URL = "http://127.0.0.1:7788"
WS_URL = "ws://127.0.0.1:7788/ws/events"


async def run_command(command: str) -> tuple[dict, list[dict]]:
    events: list[dict] = []
    async with websockets.connect(WS_URL) as socket:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
            response = await client.post("/api/tasks", json={"user_request": command})
            response.raise_for_status()
            task = response.json()
            while True:
                event = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
                if event["task_id"] != task["id"]:
                    continue
                events.append(event)
                if event["type"] in {"task_completed", "task_failed", "task_cancelled", "approval_required"}:
                    break
            stored = (await client.get(f"/api/tasks/{task['id']}")).json()
            return stored, events


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
        health = (await client.get("/health")).json()
        models = (await client.get("/api/models")).json()

    status_task, status_events = await run_command("What is my status today?")
    plan_task, plan_events = await run_command("Plan my work for today.")
    routing_task, routing_events = await run_command("Explain what model you chose.")
    close_task, close_events = await run_command("Close everything")
    approval_task, approval_events = await run_command("Send email to the client")

    status_types = {event["type"] for event in status_events}
    assert {"model_selected", "plan_ready", "visualization_requested", "task_completed"}.issubset(status_types)
    assert status_task["status"] == "completed" and status_task["result"]["ui_composition"]
    assert plan_task["status"] == "completed" and plan_task["plan"]
    assert routing_task["status"] == "completed"
    assert routing_task["result"]["ui_composition"]["objects"][0]["type"] == "model-routing"
    assert close_task["status"] == "completed"
    assert "model_selected" not in {event["type"] for event in close_events}
    assert approval_task["status"] == "needs_approval"
    assert approval_events[-1]["type"] == "approval_required"

    configured = {item["provider"]: item["configured"] for item in models["providers"]}
    print(json.dumps({
        "health": health,
        "task_ids": [status_task["id"], plan_task["id"], routing_task["id"], close_task["id"], approval_task["id"]],
        "status_events": [event["type"] for event in status_events],
        "plan_events": [event["type"] for event in plan_events],
        "routing_events": [event["type"] for event in routing_events],
        "close_events": [event["type"] for event in close_events],
        "approval_event": approval_events[-1]["type"],
        "provider_configured": configured,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

