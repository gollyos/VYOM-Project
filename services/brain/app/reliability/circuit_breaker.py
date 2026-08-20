from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType


class BreakerState(str, Enum):
    CLOSED = "closed"          # normal operation
    OPEN = "open"              # failing: requests are refused
    HALF_OPEN = "half_open"    # probing recovery


@dataclass
class Breaker:
    key: str
    failure_threshold: int
    cooldown_seconds: float
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    opened_at: float | None = None
    half_open_successes: int = 0
    last_error: str | None = None


class CircuitBreakerRegistry:
    """Circuit breakers for provider/tool/MCP/integration/network
    failures. After `failure_threshold` consecutive failures the breaker
    opens and dependent workflows stop being retried (no retry storms);
    after the cooldown it half-opens and probes."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0, event_bus: EventBus | None = None):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.event_bus = event_bus
        self._breakers: dict[str, Breaker] = {}

    def _breaker(self, key: str) -> Breaker:
        if key not in self._breakers:
            self._breakers[key] = Breaker(key, self.failure_threshold, self.cooldown_seconds)
        return self._breakers[key]

    async def _emit_opened(self, breaker: Breaker) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(BrainEvent(
            task_id="system", type=EventType.CIRCUIT_BREAKER_OPENED,
            human_readable_message=f"Circuit breaker opened for {breaker.key}",
            structured_payload={"key": breaker.key, "failures": breaker.failure_count, "last_error": breaker.last_error},
        ))

    async def allows(self, key: str) -> bool:
        breaker = self._breaker(key)
        if breaker.state == BreakerState.CLOSED:
            return True
        if breaker.state == BreakerState.OPEN:
            if breaker.opened_at is not None and time.monotonic() - breaker.opened_at >= breaker.cooldown_seconds:
                breaker.state = BreakerState.HALF_OPEN
                breaker.half_open_successes = 0
                return True
            return False
        return True  # half-open: probing

    async def record_success(self, key: str) -> None:
        breaker = self._breaker(key)
        breaker.failure_count = 0
        breaker.last_error = None
        if breaker.state == BreakerState.HALF_OPEN:
            breaker.half_open_successes += 1
            if breaker.half_open_successes >= 2:
                breaker.state = BreakerState.CLOSED
                breaker.opened_at = None

    async def record_failure(self, key: str, error: str | None = None) -> None:
        breaker = self._breaker(key)
        breaker.failure_count += 1
        breaker.last_error = error
        if breaker.state == BreakerState.HALF_OPEN or breaker.failure_count >= self.failure_threshold:
            breaker.state = BreakerState.OPEN
            breaker.opened_at = time.monotonic()
            await self._emit_opened(breaker)

    def status(self, key: str) -> dict:
        breaker = self._breaker(key)
        return {
            "key": key,
            "state": breaker.state.value,
            "failures": breaker.failure_count,
            "last_error": breaker.last_error,
        }
