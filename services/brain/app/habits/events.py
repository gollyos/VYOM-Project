from __future__ import annotations

from .schemas import HabitEvent, HabitEventSource


class UnapprovedEventSourceError(ValueError):
    pass


def build_event(
    habit_id: str, *, value: float = 1.0, source: HabitEventSource = HabitEventSource.MANUAL,
    confidence: float = 1.0, note: str | None = None, allowed_sources: set[str] | None = None,
) -> HabitEvent:
    """Constructs and validates a `HabitEvent`. Tracking is bounded to
    explicit check-ins plus existing task/calendar/system events plus
    user-approved integrations (rule 10) — an event from a source outside
    `allowed_sources` (config/habits.yaml) is rejected rather than silently
    recorded, which is the concrete enforcement of "no invasive tracking"."""
    if allowed_sources is not None and source.value not in allowed_sources:
        raise UnapprovedEventSourceError(f"Habit event source '{source.value}' is not in the approved tracking sources")
    return HabitEvent(habit_id=habit_id, value=value, source=source, confidence=confidence, note=note)
