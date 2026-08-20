from __future__ import annotations

import argparse
import asyncio
import json

import httpx
import websockets


TERMINAL_EVENTS = {"task_completed", "task_failed", "task_cancelled", "approval_required"}


async def verify(base_url: str) -> dict:
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/events"
    events: list[dict] = []
    async with websockets.connect(ws_url) as socket:
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            health = (await client.get("/health")).json()
            tools = (await client.get("/api/tools")).json()
            response = await client.post("/api/tasks", json={"user_request": "Inspect this project"})
            response.raise_for_status()
            task = response.json()
            while True:
                event = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
                if event.get("task_id") != task["id"]:
                    continue
                events.append(event)
                if event["type"] in TERMINAL_EVENTS:
                    break
            stored = (await client.get(f"/api/tasks/{task['id']}")).json()

    event_types = [event["type"] for event in events]
    required = {
        "task_created",
        "task_understanding",
        "plan_ready",
        "tool_selected",
        "tool_started",
        "tool_completed",
        "verification_evidence",
        "visualization_requested",
        "task_completed",
    }
    missing = sorted(required.difference(event_types))
    assert stored["status"] == "completed", stored
    assert not missing, f"Missing Phase 5 events: {missing}"
    assert stored["verification"]["passed"] is True
    assert all(tool["health"]["healthy"] for tool in tools["tools"])
    return {
        "health": health,
        "tool_count": len(tools["tools"]),
        "mcp_server_count": len(tools["mcp_servers"]),
        "task_id": task["id"],
        "status": stored["status"],
        "verification": stored["verification"],
        "events": event_types,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the VYOM Phase 5 HTTP/WebSocket tool path")
    parser.add_argument("--base-url", default="http://127.0.0.1:7788")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.base_url.rstrip("/"))), indent=2))


if __name__ == "__main__":
    main()
