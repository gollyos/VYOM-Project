from __future__ import annotations

from datetime import datetime, time

from .rules import ProactiveSuggestion


def _in_window(now: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # window wraps past midnight


class TimingResult:
    def __init__(self, allowed: bool, reason: str):
        self.allowed = allowed
        self.reason = reason


class TimingEvaluator:
    """Is now a good time? `critical` always bypasses quiet hours/focus
    mode/explicit quiet windows (rule 33) — nothing else does."""

    def evaluate(
        self, suggestion: ProactiveSuggestion, *, now: datetime, quiet_hours: dict | None = None,
        focus_active: bool = False, explicit_quiet_until: datetime | None = None,
    ) -> TimingResult:
        if suggestion.urgency == "critical":
            return TimingResult(True, "Critical suggestions always bypass quiet/focus timing")

        if explicit_quiet_until is not None and now < explicit_quiet_until:
            return TimingResult(False, f"User-set quiet mode is active until {explicit_quiet_until.isoformat()}")

        if focus_active and suggestion.urgency not in {"urgent", "important"}:
            return TimingResult(False, "A focus session is active; low/normal-priority suggestions are held")

        if quiet_hours:
            start = time.fromisoformat(quiet_hours.get("start", "23:00"))
            end = time.fromisoformat(quiet_hours.get("end", "07:00"))
            if _in_window(now.time(), start, end) and suggestion.urgency not in {"urgent", "important"}:
                return TimingResult(False, f"Within configured quiet hours ({quiet_hours.get('start')}-{quiet_hours.get('end')})")

        return TimingResult(True, "Timing is acceptable")
