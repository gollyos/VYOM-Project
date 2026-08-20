from __future__ import annotations

from collections import Counter
from datetime import date

from .schemas import HabitEvent, PatternInsight

TIME_BUCKETS = (
    ("early morning", range(4, 8)), ("morning", range(8, 12)), ("afternoon", range(12, 17)),
    ("evening", range(17, 21)), ("night", range(21, 24)), ("late night", range(0, 4)),
)


def _bucket(hour: int) -> str:
    for label, hours in TIME_BUCKETS:
        if hour in hours:
            return label
    return "unknown"


class HabitPatternAnalyzer:
    """Analyzes real recorded events across time-of-day, day-of-week, and
    caller-supplied context (workload, unfinished tasks, focus sessions,
    routine completion). Every insight requires the configured minimum
    sample size and confidence before it is returned (rule 12/13) — weak
    correlations come back as `None`, never as a stated fact."""

    def __init__(self, *, minimum_sample_size: int = 5, minimum_confidence: float = 0.55):
        self.minimum_sample_size = minimum_sample_size
        self.minimum_confidence = minimum_confidence

    def time_of_day_distribution(self, events: list[HabitEvent]) -> dict[str, int]:
        counts: Counter[str] = Counter(_bucket(event.timestamp.hour) for event in events)
        return dict(counts)

    def day_of_week_distribution(self, events: list[HabitEvent]) -> dict[str, int]:
        counts: Counter[str] = Counter(event.timestamp.strftime("%A") for event in events)
        return dict(counts)

    def dominant_time_insight(self, events: list[HabitEvent], habit_name: str, *, time_range: str) -> PatternInsight | None:
        if len(events) < self.minimum_sample_size:
            return None
        distribution = self.time_of_day_distribution(events)
        if not distribution:
            return None
        bucket, count = max(distribution.items(), key=lambda item: item[1])
        confidence = round(count / len(events), 4)
        if confidence < self.minimum_confidence:
            return None
        supporting = [event.id for event in events if _bucket(event.timestamp.hour) == bucket]
        return PatternInsight(
            statement=f"'{habit_name}' events occurred on {count} of {len(events)} occasions during the {bucket} window",
            sample_size=len(events), confidence=confidence, supporting_events=supporting, time_range=time_range,
        )

    def correlate_with_context_days(
        self, events: list[HabitEvent], context_days: set[date], *, habit_name: str, context_label: str, time_range: str,
    ) -> PatternInsight | None:
        """Compares occurrence rate on days flagged by `context_days`
        (e.g. days with an unfinished work session) against other days —
        the concrete mechanism behind rule 11/59's example."""
        event_days = {event.timestamp.date() for event in events}
        if len(event_days) < self.minimum_sample_size or not context_days:
            return None
        overlap = event_days & context_days
        rate = len(overlap) / len(context_days)
        if rate < self.minimum_confidence:
            return None
        supporting = [event.id for event in events if event.timestamp.date() in overlap]
        return PatternInsight(
            statement=f"'{habit_name}' occurred on {len(overlap)} of {len(context_days)} days flagged as '{context_label}'",
            sample_size=len(context_days), confidence=round(rate, 4), supporting_events=supporting, time_range=time_range,
        )
