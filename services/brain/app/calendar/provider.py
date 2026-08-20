from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta

from app.integrations.provider import IntegrationProvider

from .schemas import AvailabilityRequest, AvailabilitySlot, CalendarEvent, CalendarReceipt, CreateEventRequest


class CalendarProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def list_events(self, start_at, end_at) -> list[CalendarEvent]: ...

    @abstractmethod
    async def create_event(self, request: CreateEventRequest) -> CalendarReceipt: ...


class DisconnectedCalendarProvider(CalendarProvider):
    id = "calendar.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Calendar integration is disconnected"

    async def list_events(self, start_at, end_at) -> list[CalendarEvent]:
        raise RuntimeError("Calendar integration is disconnected")

    async def create_event(self, request: CreateEventRequest) -> CalendarReceipt:
        raise RuntimeError("Calendar integration is disconnected")


class MockCalendarProvider(CalendarProvider):
    id = "mock-calendar"

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self.events = list(events or [])

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def list_events(self, start_at, end_at) -> list[CalendarEvent]:
        return [event for event in self.events if event.end_at > start_at and event.start_at < end_at]

    async def create_event(self, request: CreateEventRequest) -> CalendarReceipt:
        event_id = f"mock-event-{len(self.events) + 1}"
        self.events.append(CalendarEvent(id=event_id, provider=self.id, **request.model_dump(exclude={"timezone"})))
        return CalendarReceipt(provider=self.id, event_id=event_id, verified=True, evidence=[f"provider_event_id:{event_id}"])

    async def availability(self, request: AvailabilityRequest) -> list[AvailabilitySlot]:
        busy = await self.list_events(request.start_at, request.end_at)
        slots: list[AvailabilitySlot] = []
        cursor = request.start_at
        step = timedelta(minutes=request.duration_minutes)
        for event in sorted(busy, key=lambda item: item.start_at):
            while cursor + step <= event.start_at:
                slots.append(AvailabilitySlot(start_at=cursor, end_at=cursor + step, timezone=request.timezone))
                cursor += step
            cursor = max(cursor, event.end_at)
        while cursor + step <= request.end_at:
            slots.append(AvailabilitySlot(start_at=cursor, end_at=cursor + step, timezone=request.timezone))
            cursor += step
        return slots
