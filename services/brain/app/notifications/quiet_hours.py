from __future__ import annotations

from datetime import datetime, timedelta, timezone


class QuietModeState:
    """"Don't disturb me for 2 hours unless it's critical" (rule 33).
    Explicit, time-bounded, automatically ends — never a manual toggle the
    user has to remember to turn back off. `critical` is the only bypass;
    everything else is suppressed and retained for later batch delivery."""

    def __init__(self) -> None:
        self._until: datetime | None = None

    def start(self, duration_minutes: float) -> datetime:
        self._until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        return self._until

    def end(self) -> None:
        self._until = None

    def is_active(self, *, now: datetime | None = None) -> bool:
        if self._until is None:
            return False
        current = now or datetime.now(timezone.utc)
        if current >= self._until:
            self._until = None  # automatically ends (rule 33)
            return False
        return True

    def until(self) -> datetime | None:
        return self._until if self.is_active() else None
