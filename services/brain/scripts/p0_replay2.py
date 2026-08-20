"""P0 failure-family replay: browser continuity + memory relevance +
idle no-action, through the PRODUCTION command bus.

Reproduces the exact utterances from the 2026-08-19 physical session and
the §15/§16/§17 acceptance shapes from the recovery brief. Before/after
world state (Chrome processes, top-level browser windows, tab list) is
read with the SAME accessibility layer the Brain uses.

Debug/regression tool only - final acceptance is the physical microphone.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx
import websockets

TERMINALS = {"task_completed", "task_failed", "task_cancelled"}


def world_snapshot() -> dict:
    import psutil

    try:
        from app.input_control.accessibility import AccessibilityController

        accessibility = AccessibilityController()
        windows = accessibility.browser_windows()
        tabs = accessibility.list_browser_tabs()
        window_titles = []
        for window in windows:
            try:
                window_titles.append(window.window_text()[:60])
            except Exception:
                window_titles.append("?")
    except Exception as error:
        window_titles = [f"unavailable: {error}"]
        tabs = []
    chrome_processes = sum(
        1 for process in psutil.process_iter(["name"])
        if (process.info.get("name") or "").lower() == "chrome.exe")
    return {
        "chrome_processes": chrome_processes,
        "browser_windows": len(window_titles),
        "window_titles": window_titles,
        "tabs": [tab.get("title", "")[:50] for tab in tabs],
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
        await asyncio.sleep(0.3)

        async with httpx.AsyncClient(base_url=base_url, timeout=120) as http:
            async def run(utterance: str) -> dict:
                before = world_snapshot()
                started = time.perf_counter()
                created = await http.post("/api/tasks", json={"user_request": utterance})
                created.raise_for_status()
                task_id = created.json()["id"]

                terminals: list[dict] = []
                deadline = time.perf_counter() + 90
                while time.perf_counter() < deadline:
                    terminals = [e for e in events if e.get("task_id") == task_id
                                 and e.get("type") in TERMINALS]
                    if terminals:
                        break
                    await asyncio.sleep(0.2)
                await asyncio.sleep(0.3)
                terminals = [e for e in events if e.get("task_id") == task_id
                             and e.get("type") in TERMINALS]
                after = world_snapshot()
                detail = (await http.get(f"/api/tasks/{task_id}")).json()
                md = detail.get("metadata") or {}
                row = {
                    "utterance": utterance,
                    "status": detail.get("status"),
                    "model": detail.get("assigned_model"),
                    "intent": (detail.get("profile") or {}).get("intent"),
                    "terminals": len(terminals),
                    "goal": (md.get("goal_verification") or {}).get("status"),
                    "response": ((detail.get("result") or {}).get("response") or "")[:160],
                    "memory_reason": (md.get("memory_selection") or {}).get("selection_reason"),
                    "chrome_proc": f"{before['chrome_processes']}->{after['chrome_processes']}",
                    "windows": f"{before['browser_windows']}->{after['browser_windows']}",
                    "tabs": f"{len(before['tabs'])}->{len(after['tabs'])}",
                    "latency_s": round(time.perf_counter() - started, 1),
                }
                print(json.dumps(row, ensure_ascii=False), flush=True)
                return row

            print("=== §15 browser continuity (real Chrome) ===", flush=True)
            await run("Chrome kholo.")
            await run("Golly AI OS profile kholo.")
            await run("Isi profile me new tab pe YouTube kholo.")
            await run("New tab me Gmail kholo.")
            await run("YouTube wala tab band karo, Chrome nahi.")

            print("\n=== §17 memory noise ===", flush=True)
            await run("Hello.")
            await run("What's my name?")
            await run("What's my website?")
            await run("What are you doing?")

            print("\n=== complaint re-check (must NOT launch) ===", flush=True)
            await run("I cannot show on the calculator this is clear.")

            print("\n=== §16 idle probe: 20s, no command ===", flush=True)
            before_events = len(events)
            before_world = world_snapshot()
            await asyncio.sleep(20)
            new_events = events[before_events:]
            effect_types = {"tool_started", "tool_progress", "tool_completed", "tool_selected"}
            stray = [e for e in new_events
                     if e.get("type") in effect_types or e.get("type") in TERMINALS]
            after_world = world_snapshot()
            idle = {
                "events_during_idle": len(new_events),
                "external_actions_during_idle": len(stray),
                "chrome_processes": f"{before_world['chrome_processes']}->{after_world['chrome_processes']}",
                "browser_windows": f"{before_world['browser_windows']}->{after_world['browser_windows']}",
                "tabs": f"{len(before_world['tabs'])}->{len(after_world['tabs'])}",
            }
            print(json.dumps(idle, ensure_ascii=False))

        listener.cancel()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7788")
    raise SystemExit(asyncio.run(main(parser.parse_args().base_url)))
