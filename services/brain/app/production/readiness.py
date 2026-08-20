from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReadinessState:
    """alive / ready / degraded, distinguished explicitly: the Brain
    can be alive (process serving) but not ready (e.g. a migration
    failed). `/healthz` answers alive; `/readyz` answers ready."""

    alive: bool = True
    ready: bool = False
    degraded_reasons: list[str] = None

    def __post_init__(self):
        if self.degraded_reasons is None:
            self.degraded_reasons = []

    def as_dict(self) -> dict:
        state = "ready" if self.ready and self.alive else ("degraded" if self.alive else "down")
        return {"alive": self.alive, "ready": self.ready, "state": state, "reasons": self.degraded_reasons}


class ReadinessTracker:
    def __init__(self):
        self._state = ReadinessState(alive=True, ready=False)

    def mark_ready(self) -> None:
        self._state.ready = True
        self._state.degraded_reasons = []

    def mark_degraded(self, reasons: list[str]) -> None:
        self._state.ready = False
        self._state.degraded_reasons = list(reasons)

    def mark_down(self) -> None:
        self._state.alive = False
        self._state.ready = False

    @property
    def state(self) -> ReadinessState:
        return self._state

    def snapshot(self) -> dict:
        return self._state.as_dict()
