"""Live "where has the work reached" board.

VYOM could already answer "what are you doing" from the task store, but a
multi-agent task looked like a single opaque `executing` row - the user
could not see WHICH agent was on it or what step it was at. This tracker
subscribes to the one event bus every execution path already publishes
through and keeps a small per-task board: the current phase, the ordered
list of steps seen, and one row per delegated agent (queued / working /
done / failed, with its last message).

It is read by `_answer_runtime_introspection` (so "kaam kaha pahuncha?"
now names the agent and step) and by `GET /api/tasks/{id}/progress`.
Pure in-memory, bounded, zero model cost.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas.events import BrainEvent, EventType

_TERMINAL = {EventType.TASK_COMPLETED, EventType.TASK_FAILED, EventType.TASK_CANCELLED}
_AGENT_START = {EventType.AGENT_STARTED, EventType.AGENT_DELEGATED}
_AGENT_DONE = {EventType.AGENT_COMPLETED}
_AGENT_FAIL = {EventType.AGENT_FAILED}


def _now() -> float:
    return time.time()


@dataclass
class AgentProgress:
    agent_id: str
    goal: str = ""
    status: str = "queued"  # queued | working | done | failed
    last_message: str = ""
    started_at: float | None = None
    updated_at: float = field(default_factory=_now)


@dataclass
class TaskProgress:
    task_id: str
    phase: str = "queued"
    last_message: str = ""
    steps: list[str] = field(default_factory=list)
    agents: "OrderedDict[str, AgentProgress]" = field(default_factory=OrderedDict)
    started_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    done: bool = False
    outcome: str | None = None  # completed | failed | cancelled

    # -- rendering ----------------------------------------------------

    def describe(self) -> str:
        """One plain sentence: where the work has reached."""
        age = int(_now() - self.started_at)
        if self.done:
            head = f"That task {self.outcome or 'finished'} after {age}s"
        else:
            head = f"That task is at: {self.phase} ({age}s in)"
        if not self.agents:
            tail = self.last_message or ""
            return f"{head}. {tail}".strip()

        working = [a for a in self.agents.values() if a.status == "working"]
        done = [a for a in self.agents.values() if a.status == "done"]
        failed = [a for a in self.agents.values() if a.status == "failed"]
        queued = [a for a in self.agents.values() if a.status == "queued"]
        parts: list[str] = []
        for a in working:
            since = int(_now() - (a.started_at or a.updated_at))
            msg = f" - {a.last_message}" if a.last_message else ""
            parts.append(f"{a.agent_id} is working ({since}s){msg}")
        if queued:
            parts.append(f"{', '.join(a.agent_id for a in queued)} queued")
        if done:
            parts.append(f"{len(done)}/{len(self.agents)} done ({', '.join(a.agent_id for a in done)})")
        if failed:
            parts.append(f"{', '.join(a.agent_id for a in failed)} failed")
        return f"{head}. " + "; ".join(parts) + "."

    def snapshot(self) -> dict:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "done": self.done,
            "outcome": self.outcome,
            "last_message": self.last_message,
            "elapsed_seconds": int(_now() - self.started_at),
            "steps": list(self.steps),
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "goal": a.goal,
                    "status": a.status,
                    "last_message": a.last_message,
                    "elapsed_seconds": int(_now() - a.started_at) if a.started_at else None,
                }
                for a in self.agents.values()
            ],
            "updated_at": datetime.fromtimestamp(self.updated_at, tz=timezone.utc).isoformat(),
        }


class ProgressTracker:
    def __init__(self, max_tasks: int = 128):
        self._tasks: "OrderedDict[str, TaskProgress]" = OrderedDict()
        self._max_tasks = max_tasks

    # -- ingestion ---------------------------------------------------

    def observe(self, event: BrainEvent) -> None:
        board = self._tasks.get(event.task_id)
        if board is None:
            board = TaskProgress(task_id=event.task_id)
            self._tasks[event.task_id] = board
            while len(self._tasks) > self._max_tasks:
                self._tasks.popitem(last=False)
        board.updated_at = _now()
        msg = (event.human_readable_message or "").strip()
        payload = event.structured_payload or {}

        agent_id = self._agent_id_from(payload)

        if event.type in _AGENT_START and agent_id:
            ap = board.agents.get(agent_id) or AgentProgress(agent_id=agent_id)
            ap.status = "working"
            ap.started_at = ap.started_at or _now()
            ap.updated_at = _now()
            if payload.get("mission", {}).get("goal"):
                ap.goal = str(payload["mission"]["goal"])[:200]
            if msg:
                ap.last_message = msg[:200]
            board.agents[agent_id] = ap
            board.phase = f"delegating to {agent_id}"
        elif event.type in _AGENT_DONE and agent_id:
            ap = board.agents.get(agent_id) or AgentProgress(agent_id=agent_id)
            ap.status = "done"
            ap.updated_at = _now()
            if msg:
                ap.last_message = msg[:200]
            board.agents[agent_id] = ap
        elif event.type in _AGENT_FAIL and agent_id:
            ap = board.agents.get(agent_id) or AgentProgress(agent_id=agent_id)
            ap.status = "failed"
            ap.updated_at = _now()
            if msg:
                ap.last_message = msg[:200]
            board.agents[agent_id] = ap
        elif event.type in _TERMINAL:
            board.done = True
            board.outcome = {
                EventType.TASK_COMPLETED: "completed",
                EventType.TASK_FAILED: "failed",
                EventType.TASK_CANCELLED: "cancelled",
            }.get(event.type)
            board.phase = board.outcome or "finished"
            if msg:
                board.last_message = msg[:300]
        else:
            # A generic progress / planning / model-selected event.
            if msg:
                board.last_message = msg[:300]
                if event.type in (EventType.TASK_PROGRESS, EventType.TASK_PLANNING,
                                  EventType.TASK_UNDERSTANDING):
                    if not board.steps or board.steps[-1] != msg[:120]:
                        board.steps.append(msg[:120])
                        board.steps[:] = board.steps[-20:]
            phase = self._phase_from(event.type)
            if phase and not board.done:
                board.phase = phase
            # Keep an active agent's running commentary fresh.
            if agent_id and agent_id in board.agents and board.agents[agent_id].status == "working" and msg:
                board.agents[agent_id].last_message = msg[:200]
                board.agents[agent_id].updated_at = _now()

    @staticmethod
    def _agent_id_from(payload: dict) -> str | None:
        for key in ("agent_id", "agent", "to", "delegate_to"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        agent = payload.get("agent")
        if isinstance(agent, dict):
            return agent.get("id") or agent.get("agent_id")
        mission = payload.get("mission")
        if isinstance(mission, dict) and mission.get("agent_id"):
            return mission["agent_id"]
        return None

    @staticmethod
    def _phase_from(event_type: EventType) -> str | None:
        return {
            EventType.TASK_UNDERSTANDING: "understanding",
            EventType.TASK_PLANNING: "planning",
            EventType.PLAN_READY: "planning",
            EventType.MODEL_SELECTED: "planning",
            EventType.TASK_PROGRESS: "executing",
            EventType.VERIFICATION_STARTED: "verifying",
        }.get(event_type)

    # -- reads -----------------------------------------------------

    def get(self, task_id: str) -> TaskProgress | None:
        return self._tasks.get(task_id)

    def snapshot(self, task_id: str) -> dict | None:
        board = self._tasks.get(task_id)
        return board.snapshot() if board else None

    def latest_running(self) -> TaskProgress | None:
        for board in reversed(self._tasks.values()):
            if not board.done:
                return board
        return None

    def describe_active(self) -> str | None:
        """One line about the most recent still-running task, if any has a
        sub-agent breakdown worth showing."""
        board = self.latest_running()
        if board is None or not board.agents:
            return None
        return board.describe()
