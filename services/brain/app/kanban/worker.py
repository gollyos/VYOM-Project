#!/usr/bin/env python3
"""Kanban worker - runs as an isolated OS subprocess spawned by the
dispatcher (app/kanban/dispatcher.py), mirroring Hermes's own kanban
worker pattern (a separate `hermes -p <profile>` process per claimed
task). Rather than re-import and duplicate TaskRuntime's construction
inside a second process (a second DB connection racing the main
process's WAL writer), this worker submits its card's goal through the
Brain's own HTTP API - the exact same production task pipeline a real
user request goes through - polls for completion, then reports the
result back to the kanban card via the API. This keeps "the worker is a
real separate process" true while reusing one authoritative execution
path instead of a second one that could drift from it.

Usage: python -m app.kanban.worker <card_id> <goal> [--base-url URL]
"""
from __future__ import annotations

import argparse
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import json


def _post(url: str, payload: dict, timeout: float = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(url: str, timeout: float = 30) -> dict:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_worker(card_id: str, goal: str, base_url: str, *, poll_seconds: float = 2, timeout_seconds: float = 300) -> int:
    try:
        task = _post(f"{base_url}/api/tasks", {
            "user_request": goal, "context_id": f"kanban:{card_id}", "source": "kanban",
        })
    except URLError as error:
        _post(f"{base_url}/api/kanban/cards/{card_id}/fail", {"error": f"Could not submit task: {error}"})
        return 1

    task_id = task["id"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        try:
            polled = _get(f"{base_url}/api/tasks/{task_id}")
        except URLError:
            continue
        status = polled.get("status")
        if status == "completed":
            result = (polled.get("result") or {}).get("response", "")
            _post(f"{base_url}/api/kanban/cards/{card_id}/complete", {"response": result, "task_id": task_id})
            return 0
        if status in ("failed", "cancelled"):
            error = polled.get("error") or f"Task ended with status={status}"
            _post(f"{base_url}/api/kanban/cards/{card_id}/fail", {"error": error})
            return 1

    _post(f"{base_url}/api/kanban/cards/{card_id}/fail", {"error": f"Timed out after {timeout_seconds}s"})
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("card_id")
    parser.add_argument("goal")
    parser.add_argument("--base-url", default="http://127.0.0.1:7788")
    args = parser.parse_args()
    return run_worker(args.card_id, args.goal, args.base_url)


if __name__ == "__main__":
    sys.exit(main())
