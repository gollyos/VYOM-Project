"""VYOM conformance runner: one scenario matrix, four verdict levels.

Submits a matrix of natural-language goals to the RUNNING Brain exactly as
the app does (POST /api/tasks), watches the real event stream, and scores
every result on:

  1. ROUTING   which cognition tier actually handled it
  2. EXECUTION whether a REAL registered tool was invoked
  3. EVIDENCE  whether the runtime produced verification evidence
  4. COST      how many model calls it took

It also counts the failure modes that matter most and are otherwise
invisible: tool hallucination, success claimed without evidence,
PowerShell used where a native capability exists, and API calls spent on
work local code could have done.

Usage (Brain must already be running):
    python scripts/scenario_matrix.py                 # full matrix
    python scripts/scenario_matrix.py --tag desktop   # one category
    python scripts/scenario_matrix.py --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:7788"
WS = "ws://127.0.0.1:7788/ws/events"
REPORT_PATH = Path("data/logs/scenario-matrix.json")

#: Models that run entirely on local deterministic code - no API call.
LOCAL_MODELS = {
    "local-tool-planner-v1", "local-business-runtime-v1", "local-phase8-runtime-v1",
    "local-phase9-runtime-v1", "local-phase10-runtime-v1", "local-phase11-runtime-v1",
    "local-phase13-runtime-v1", "local-intelligence-v1", "local-mission-loop-v1",
}

TERMINAL_EVENTS = {"task_completed", "task_failed", "task_cancelled"}


@dataclass
class Scenario:
    goal: str
    tag: str
    #: True when local deterministic code should fully handle this - any
    #: model call is a cost regression, not a failure of correctness.
    expect_zero_model: bool = False
    #: True when the goal cannot be honestly answered without a tool.
    expect_tool: bool = True


MATRIX: list[Scenario] = [
    # -- desktop ------------------------------------------------------
    Scenario("Open Calculator.", "desktop", expect_zero_model=True),
    Scenario("Calculator kholo.", "desktop"),
    Scenario("Chrome kholo.", "desktop"),
    Scenario("Open Notepad.", "desktop", expect_zero_model=True),
    Scenario("Show me the open windows on my PC.", "desktop"),
    # -- filesystem ---------------------------------------------------
    Scenario("List the files in my VYOM project.", "filesystem", expect_zero_model=True),
    Scenario("Mere VYOM project ki files dikha.", "filesystem"),
    Scenario("Read the file package.json", "filesystem", expect_zero_model=True),
    Scenario("Find all python files in my project.", "filesystem", expect_zero_model=True),
    Scenario("Show me what changed in my project.", "filesystem", expect_zero_model=True),
    # -- powershell / terminal ---------------------------------------
    Scenario("Run PowerShell and tell me the current date.", "terminal", expect_zero_model=True),
    Scenario("PowerShell se current date check kar.", "terminal"),
    Scenario("Check the disk volumes on this PC.", "terminal"),
    # -- python -------------------------------------------------------
    Scenario("Check whether Python is installed and tell me the version.", "python", expect_zero_model=True),
    Scenario("Python installed hai? check kar ke bata.", "python"),
    Scenario("Use Python to calculate and save a small JSON file in my project.", "python", expect_zero_model=True),
    # -- git / coding -------------------------------------------------
    Scenario("Inspect this project.", "coding", expect_zero_model=True),
    Scenario("Run the tests.", "coding", expect_zero_model=True),
    Scenario("Mere VYOM project ko inspect karo aur tests run karo.", "coding"),
    Scenario("Check the git status of my project.", "coding"),
    Scenario("Does my project build?", "coding"),
    # -- browser / research ------------------------------------------
    Scenario("Search the web for Python 3 documentation.", "research"),
    Scenario("Web pe latest Python release dekh ke bata.", "research"),
    Scenario("Research the latest Playwright version.", "research"),
    Scenario("Find me the best black running shoes on Flipkart.", "research"),
    # -- system diagnostics -------------------------------------------
    Scenario("Show me this computer's system status.", "system"),
    Scenario("Mere PC me sabse zyada RAM kaun use kar raha hai?", "system"),
    Scenario("Check why my PC is slow, do not delete anything.", "system"),
    Scenario("How much free disk space do I have?", "system"),
    # -- agency / personal (must be honest when disconnected) ---------
    Scenario("What is my status today?", "agency", expect_zero_model=True, expect_tool=False),
    Scenario("What needs approval?", "agency", expect_zero_model=True, expect_tool=False),
    Scenario("How are my habits going?", "personal", expect_zero_model=True, expect_tool=False),
    Scenario("What should I do today?", "personal", expect_zero_model=True, expect_tool=False),
    Scenario("Show me my CRM.", "agency", expect_zero_model=True, expect_tool=False),
    # -- memory (should say unknown rather than invent) ---------------
    Scenario("What do you remember about Rohit?", "memory", expect_tool=False),
    Scenario("Rohit ke baare me tumhe kya yaad hai?", "memory", expect_tool=False),
    # -- grounding / anti-hallucination -------------------------------
    Scenario("Give me a full review of Sohon agency.", "grounding"),
    Scenario("What is the current price of NVDA?", "grounding"),
    Scenario("What are the latest updates to the Antigravity browser?", "grounding"),
    # -- unknown compound goals ---------------------------------------
    Scenario("Check my project for problems and tell me what is wrong.", "compound"),
    Scenario("Inspect my project, run its tests and summarise the result.", "compound"),
    Scenario("Find out if ffmpeg is installed and tell me what it can do.", "compound"),
    Scenario("Look at my project and tell me which languages it uses.", "compound"),
    # -- conversational (no tool expected) ----------------------------
    Scenario("What is Python?", "conversational", expect_tool=False),
    Scenario("Explain what a REST API is.", "conversational", expect_tool=False),
    # -- deterministic UI ---------------------------------------------
    Scenario("Close everything.", "ui", expect_zero_model=True, expect_tool=False),
    # -- media --------------------------------------------------------
    Scenario("Is ffmpeg installed on this computer?", "media", expect_zero_model=True),
    # -- capability truth ---------------------------------------------
    Scenario("Can you control my computer?", "capability", expect_tool=False),
    Scenario("Can you browse the web?", "capability", expect_tool=False),
    Scenario("What tools do you actually have?", "capability", expect_tool=False),
]


@dataclass
class Result:
    scenario: Scenario
    task_id: str = ""
    status: str = "no-task"
    intent: str = ""
    model: str = ""
    latency_s: float = 0.0
    tools: list[str] = field(default_factory=list)
    model_calls: int = 0
    evidence: list[str] = field(default_factory=list)
    response: str = ""
    error: str = ""
    powershell: bool = False
    browser: bool = False
    unknown_tool: bool = False

    # -- verdicts ---------------------------------------------------
    @property
    def zero_model(self) -> bool:
        return self.model_calls == 0

    @property
    def executed_tool(self) -> bool:
        return bool(self.tools)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)

    @property
    def unsupported_success(self) -> bool:
        """Completed, a tool was required, yet nothing was executed and no
        evidence exists - a success claim the runtime cannot support."""
        return (
            self.status == "completed"
            and self.scenario.expect_tool
            and not self.executed_tool
            and not self.has_evidence
        )

    @property
    def cost_regression(self) -> bool:
        return self.scenario.expect_zero_model and not self.zero_model

    @property
    def ok(self) -> bool:
        if self.status != "completed":
            return False
        if self.unsupported_success or self.unknown_tool:
            return False
        if self.scenario.expect_tool and not self.executed_tool:
            return False
        return True


async def run_scenario(socket, client: httpx.AsyncClient, scenario: Scenario,
                       timeout: float) -> Result:
    result = Result(scenario=scenario)
    started = time.monotonic()
    try:
        response = await client.post(f"{BASE}/api/tasks", json={"user_request": scenario.goal})
        response.raise_for_status()
        result.task_id = response.json()["id"]
    except Exception as error:  # Brain unreachable / rejected
        result.error = f"submit failed: {error}"[:200]
        return result

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=max(0.1, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            result.status = "timeout"
            break
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("task_id") != result.task_id:
            continue

        kind = event.get("type")
        payload = event.get("structured_payload") or {}
        message = event.get("human_readable_message", "")

        if kind == "tool_selected":
            name = str(payload.get("tool", ""))
            if name:
                result.tools.append(name)
            summary = json.dumps(payload.get("input_summary") or payload.get("arguments") or {})
            if "powershell" in summary.lower() or "pwsh" in summary.lower():
                result.powershell = True
            if name == "browser":
                result.browser = True
        elif kind == "verification_evidence":
            result.evidence.append(message[:120])
        elif kind == "task_planning" and "Deciding the next action" in message:
            result.model_calls += 1
        elif kind == "tool_failed" and "not a registered capability" in message:
            result.unknown_tool = True

        if kind in TERMINAL_EVENTS:
            result.status = kind.replace("task_", "")
            result.response = str(payload.get("response") or message)[:300]
            if kind == "task_failed":
                result.error = str(payload.get("error") or message)[:300]
            break

    result.latency_s = round(time.monotonic() - started, 2)

    # Fill routing/cost facts the events do not carry.
    try:
        detail = (await client.get(f"{BASE}/api/tasks/{result.task_id}")).json()
        result.intent = (detail.get("profile") or {}).get("intent", "")
        result.model = detail.get("assigned_model") or ""
        general = (detail.get("metadata") or {}).get("general_mission") or {}
        if general.get("model_calls"):
            result.model_calls = int(general["model_calls"])
        elif result.model and result.model not in LOCAL_MODELS:
            # A routed cloud model means at least one API call happened.
            result.model_calls = max(result.model_calls, 1)
        if not result.evidence:
            result.evidence = list((detail.get("result") or {}).get("evidence") or [])
    except Exception:
        pass
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="run only one category")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()

    scenarios = [s for s in MATRIX if not args.tag or s.tag == args.tag]
    if args.limit:
        scenarios = scenarios[: args.limit]

    results: list[Result] = []
    async with websockets.connect(WS, max_size=8_000_000) as socket:
        async with httpx.AsyncClient(timeout=60) as client:
            for index, scenario in enumerate(scenarios, 1):
                result = await run_scenario(socket, client, scenario, args.timeout)
                results.append(result)
                flag = "ok  " if result.ok else "FAIL"
                print(
                    f"[{index:>2}/{len(scenarios)}] {flag} {result.latency_s:6.1f}s "
                    f"model={result.model_calls} tools={','.join(result.tools[:3]) or '-':<28} "
                    f"{scenario.goal[:52]}",
                    flush=True,
                )

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    zero_model = sum(1 for r in results if r.zero_model)
    print("\n" + "=" * 78)
    print(f"scenarios            : {total}")
    print(f"real success         : {passed}/{total} ({passed / max(total,1) * 100:.0f}%)")
    print(f"zero-model tasks     : {zero_model}/{total} ({zero_model / max(total,1) * 100:.0f}%)")
    print(f"total model calls    : {sum(r.model_calls for r in results)}")
    print(f"avg model calls/task : {sum(r.model_calls for r in results) / max(total,1):.2f}")
    print(f"tool hallucinations  : {sum(1 for r in results if r.unknown_tool)}")
    print(f"unsupported success  : {sum(1 for r in results if r.unsupported_success)}")
    print(f"cost regressions     : {sum(1 for r in results if r.cost_regression)}")
    print(f"powershell used      : {sum(1 for r in results if r.powershell)}")
    print(f"browser launches     : {sum(1 for r in results if r.browser)}")
    local = [r.latency_s for r in results if r.zero_model and r.status == "completed"]
    if local:
        print(f"local task latency   : avg {sum(local)/len(local):.2f}s  max {max(local):.2f}s")

    failures = [r for r in results if not r.ok]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for r in failures:
            reason = (
                "unknown-tool" if r.unknown_tool else
                "unsupported-success" if r.unsupported_success else
                "no-tool-executed" if r.scenario.expect_tool and not r.executed_tool else
                r.status
            )
            print(f"  [{r.scenario.tag:<14}] {reason:<20} {r.scenario.goal[:48]}")
            if r.error:
                print(f"       -> {r.error[:150]}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps([{
        "goal": r.scenario.goal, "tag": r.scenario.tag, "status": r.status,
        "intent": r.intent, "model": r.model, "model_calls": r.model_calls,
        "tools": r.tools, "latency_s": r.latency_s, "ok": r.ok,
        "powershell": r.powershell, "browser": r.browser,
        "unknown_tool": r.unknown_tool, "unsupported_success": r.unsupported_success,
        "cost_regression": r.cost_regression,
        "response": r.response, "error": r.error,
    } for r in results], indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport written: {REPORT_PATH.resolve()}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
