from __future__ import annotations

import time
from collections import deque
from enum import Enum

from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class HealthCheck:
    """A registered lightweight check. Checks must be cheap and
    deterministic — no LLM calls ever happen inside health monitoring."""

    def __init__(self, component: str, check, *, degraded_message: str = "component reported degraded"):
        self.component = component
        self.check = check  # async () -> HealthState
        self.degraded_message = degraded_message


class HealthAggregator:
    """Aggregates component health (Brain, DB, task runtime, providers,
    tools, MCP, email/calendar, browser worker, nodes, scheduler) into
    overall system health with healthy/degraded/offline/unknown
    states, and emits HEALTH_DEGRADED events on transitions."""

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus
        self._checks: dict[str, HealthCheck] = {}
        self._last_states: dict[str, HealthState] = {}
        self.started_at = time.monotonic()

    def register(self, component: str, check) -> None:
        self._checks[component] = HealthCheck(component, check)

    async def assess(self) -> dict:
        report: dict[str, str] = {}
        for component, health_check in self._checks.items():
            try:
                state = await health_check.check()
                if not isinstance(state, HealthState):
                    state = HealthState(state)
            except Exception:
                state = HealthState.UNKNOWN
            report[component] = state.value
            previous = self._last_states.get(component)
            if state == HealthState.DEGRADED and previous != HealthState.DEGRADED and self.event_bus is not None:
                # BACKGROUND_HEALTH. Telemetry is not a user mission: it
                # must never take over the foreground, interrupt work in
                # progress, or become the thing VYOM says out loud. It is
                # tagged here and the UI keeps it out of the foreground -
                # this is what stopped unrequested CPU/RAM cards from
                # appearing while the user was waiting on something else.
                await self.event_bus.publish(BrainEvent(
                    task_id="system", type=EventType.HEALTH_DEGRADED,
                    human_readable_message=f"{component} is degraded",
                    structured_payload={
                        "component": component,
                        "channel": "BACKGROUND_HEALTH",
                        "background": True,
                    },
                ))
            self._last_states[component] = state

        values = list(report.values())
        if not values or all(value == HealthState.OFFLINE.value for value in values):
            overall = HealthState.OFFLINE
        elif any(value in (HealthState.DEGRADED.value, HealthState.OFFLINE.value) for value in values):
            overall = HealthState.DEGRADED
        elif any(value == HealthState.UNKNOWN.value for value in values):
            overall = HealthState.UNKNOWN
        else:
            overall = HealthState.HEALTHY
        return {"overall": overall.value, "components": report}


class ReliabilityMetrics:
    """Reliability signals computed from real recorded outcomes only —
    task success/recovery counts, uptime, automation success, provider
    failures, queue depth, average task latency. For reliability
    monitoring, not permanent UI clutter."""

    def __init__(self):
        self.task_outcomes: deque[tuple[str, float]] = deque(maxlen=200)
        self.recovery_count = 0
        self.started_at = time.monotonic()
        self.provider_failures: deque[tuple[str, float]] = deque(maxlen=200)
        self.queue_depth_samples: deque[tuple[float, int]] = deque(maxlen=100)

    def record_task_outcome(self, outcome: str, latency_ms: float) -> None:
        self.task_outcomes.append((outcome, latency_ms))

    def record_recovery(self) -> None:
        self.recovery_count += 1

    def record_provider_failure(self, provider: str) -> None:
        self.provider_failures.append((provider, time.monotonic()))

    def record_queue_depth(self, depth: int) -> None:
        self.queue_depth_samples.append((time.monotonic(), depth))

    def snapshot(self) -> dict:
        outcomes = list(self.task_outcomes)
        completed = [item for item in outcomes if item[0] == "completed"]
        success_rate = len(completed) / len(outcomes) if outcomes else None
        latencies = [item[1] for item in completed] or None
        recent_failures: dict[str, int] = {}
        for provider, _ in self.provider_failures:
            recent_failures[provider] = recent_failures.get(provider, 0) + 1
        latest_depth = self.queue_depth_samples[-1][1] if self.queue_depth_samples else 0
        return {
            "task_success_rate": success_rate,
            "task_recovery_count": self.recovery_count,
            "uptime_seconds": round(time.monotonic() - self.started_at, 1),
            "average_task_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
            "provider_failure_counts": recent_failures,
            "queue_depth": latest_depth,
        }
