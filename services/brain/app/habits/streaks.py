from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from .schemas import HabitEvent


class StreakResult(BaseModel):
    current_streak_days: int
    longest_streak_days: int
    consistency_trend_pct: float   # % of days with an event over the lookback window
    streak_recently_broken: bool


class StreakCalculator:
    """Streaks are supported but are never the core psychology (rule 14):
    a broken streak is reported alongside — never instead of — the
    longer-window consistency trend, and breaking a streak never resets
    `consistency_trend_pct` to zero."""

    def compute(self, events: list[HabitEvent], *, lookback_days: int = 30, today: date | None = None) -> StreakResult:
        current_day = today or date.today()
        event_days = sorted({event.timestamp.date() for event in events})
        event_day_set = set(event_days)

        current_streak = 0
        cursor = current_day
        while cursor in event_day_set:
            current_streak += 1
            cursor -= timedelta(days=1)
        streak_recently_broken = current_streak == 0 and bool(event_days) and (current_day - event_days[-1]).days <= 3

        longest_streak = 0
        running = 0
        previous_day: date | None = None
        for day in event_days:
            if previous_day is not None and (day - previous_day).days == 1:
                running += 1
            else:
                running = 1
            longest_streak = max(longest_streak, running)
            previous_day = day

        window_start = current_day - timedelta(days=lookback_days)
        days_with_event = sum(1 for day in event_day_set if window_start <= day <= current_day)
        consistency_trend = round((days_with_event / lookback_days) * 100, 2) if lookback_days else 0.0

        return StreakResult(
            current_streak_days=current_streak, longest_streak_days=longest_streak,
            consistency_trend_pct=consistency_trend, streak_recently_broken=streak_recently_broken,
        )
