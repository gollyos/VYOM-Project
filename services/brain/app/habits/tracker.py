from __future__ import annotations

from .events import build_event
from .schemas import Habit, HabitEvent, HabitEventSource, HabitStatus
from .store import HabitEventStore, HabitStore


class HabitTracker:
    def __init__(self, habit_store: HabitStore, event_store: HabitEventStore, *, allowed_sources: set[str] | None = None):
        self.habit_store = habit_store
        self.event_store = event_store
        self.allowed_sources = allowed_sources

    async def create(self, habit: Habit) -> Habit:
        return await self.habit_store.save(habit)

    async def get_or_create(self, name: str, **defaults) -> Habit:
        existing = await self.habit_store.find_by_name(name)
        if existing is not None:
            return existing
        return await self.habit_store.save(Habit(name=name, **defaults))

    async def check_in(
        self, habit_id: str, *, value: float = 1.0, source: HabitEventSource = HabitEventSource.MANUAL,
        confidence: float = 1.0, note: str | None = None,
    ) -> HabitEvent:
        habit = await self.habit_store.get(habit_id)
        if habit is None:
            raise KeyError(habit_id)
        if habit.status != HabitStatus.ACTIVE:
            raise ValueError(f"Habit '{habit.name}' is not being tracked (status={habit.status.value})")
        event = build_event(habit_id, value=value, source=source, confidence=confidence, note=note, allowed_sources=self.allowed_sources)
        return await self.event_store.save(event)

    async def disable(self, habit_id: str) -> Habit:
        """User authority: "Do not track this habit" always wins (rule 70).
        Past events are preserved as a factual record; only future
        tracking stops."""
        habit = await self.habit_store.get(habit_id)
        if habit is None:
            raise KeyError(habit_id)
        habit.status = HabitStatus.ARCHIVED
        return await self.habit_store.save(habit)

    async def pause(self, habit_id: str) -> Habit:
        habit = await self.habit_store.get(habit_id)
        if habit is None:
            raise KeyError(habit_id)
        habit.status = HabitStatus.PAUSED
        return await self.habit_store.save(habit)

    async def events(self, habit_id: str, *, since=None) -> list[HabitEvent]:
        return await self.event_store.list_for_habit(habit_id, since=since)
