"""P0 control-cluster replay through the PRODUCTION command bus.

Posts the exact utterances that failed in the 2026-08-17 physical-microphone
session to the same HTTP endpoint the voice frontend uses, and observes the
same WebSocket event stream the desktop consumes - so "one terminal event"
and "no filesystem call for STOP" are measured on the real channel, not
inferred from internals.

Usage:  python scripts/p0_replay.py [--base-url http://127.0.0.1:7788]

This is a DEBUG/REGRESSION tool. Final acceptance is the physical
microphone against the release build (see the continuation instructions).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import websockets

#: (utterance, what must be true in the evidence)
REPLAY: list[tuple[str, str]] = [
    ("Stop. Stop. Stop.", "kernel interrupt; 0 model; no tool call"),
    ("guerra rua", "STT noise gate; honest re-ask; 0 model"),
    ("Calculator kholo.", "real visible Calculator; 0 model"),
    ("Calculator band karo.", "Calculator gone; 0 model"),
    ("Screen pe abhi kya hai?", "fresh window observation"),
    ("Mera naam kya hai?", "structured memory lookup; 0 model"),
    ("What are you doing right now?", "runtime introspection; 0 model"),
    ("Open the Chrome.", "visible Chrome; semantic response; no pid"),
]

TERMINALS = {"task_completed", "task_failed", "task_cancelled"}
TOOL_EVENTS = {
    "tool_started", "tool_progress", "tool_completed", "tool_failed",
    "tool_selected", "tool_permission_check",
}


async def main(base_url: str) -> int:
    ws_url = base_url.replace("http", "ws") + "/ws/events"
    events: list[dict] = []

    async with websockets.connect(ws_url, max_size=2**22) as socket:
        async def record() -> None:
            try:
                async for message in socket:
                    try:
                        events.append(json.loads(message))
                    except json.JSONDecodeError:
                        pass
            except websockets.ConnectionClosed:
                pass

        listener = asyncio.create_task(record())
        await asyncio.sleep(0.3)  # let the subscription register

        report: list[dict] = []
        async with httpx.AsyncClient(base_url=base_url, timeout=90) as http:
            for utterance, expectation in REPLAY:
                started = time.perf_counter()
                created = await http.post("/api/tasks", json={"user_request": utterance})
                created.raise_for_status()
                task_id = created.json()["id"]

                terminal_events: list[dict] = []
                deadline = time.perf_counter() + 75
                while time.perf_counter() < deadline:
                    terminal_events = [
                        event for event in events
                        if event.get("task_id") == task_id
                        and event.get("type") in TERMINALS
                    ]
                    if terminal_events:
                        break
                    await asyncio.sleep(0.1)

                await asyncio.sleep(0.15)  # catch a trailing duplicate
                terminal_events = [
                    event for event in events
                    if event.get("task_id") == task_id
                    and event.get("type") in TERMINALS
                ]
                task_events = [event for event in events if event.get("task_id") == task_id]
                tool_types = {event["type"] for event in task_events} & TOOL_EVENTS

                detail = await http.get(f"/api/tasks/{task_id}")
                task = detail.json() if detail.status_code == 200 else {}
                metadata = task.get("metadata") or {}

                report.append({
                    "utterance": utterance,
                    "expectation": expectation,
                    "task_id": task_id,
                    "status": task.get("status"),
                    "assigned_model": task.get("assigned_model"),
                    "response": ((task.get("result") or {}).get("response") or "")[:220],
                    "terminal_events": [event["type"] for event in terminal_events],
                    "tool_events": sorted(tool_types),
                    "stt_noise": metadata.get("stt_noise", False),
                    "kernel_interrupt": metadata.get("kernel_interrupt", False),
                    "goal_verification": (metadata.get("goal_verification") or {}).get("status"),
                    "general_mission_model_calls": (metadata.get("general_mission") or {}).get("model_calls"),
                    "latency_s": round(time.perf_counter() - started, 1),
                })
                print(json.dumps(report[-1], ensure_ascii=False), flush=True)

        listener.cancel()

    print("\n=== SUMMARY ===")
    bad = 0
    for row in report:
        problems = []
        if len(row["terminal_events"]) != 1:
            problems.append(f"terminal_events={row['terminal_events']}")
        if row["utterance"].startswith("Stop") and row["tool_events"]:
            problems.append(f"STOP used tools: {row['tool_events']}")
        if row["utterance"] == "guerra rua" and not row["stt_noise"]:
            problems.append("noise not gated")
        text = row["response"]
        if "pid" in text.lower() or text.strip().startswith("{"):
            problems.append(f"raw internals in response: {text[:80]}")
        if problems:
            bad += 1
        print(f"[{'FAIL' if problems else ' ok '}] {row['utterance'][:44]:<46} "
              f"model={row['assigned_model']} terminals={len(row['terminal_events'])} "
              f"goal={row['goal_verification']}")
        for problem in problems:
            print(f"        -> {problem}")
    return 1 if bad else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7788")
    raise SystemExit(
        asyncio.run(main(parser.parse_args().base_url))
    )
