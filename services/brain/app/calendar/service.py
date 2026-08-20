from __future__ import annotations

from datetime import timedelta

from .provider import CalendarProvider
from .schemas import AvailabilityRequest, AvailabilitySlot, CalendarEvent, CalendarReceipt, CreateEventRequest


class CalendarService:
    def __init__(self, provider: CalendarProvider) -> None:
        self.provider = provider

    async def events(self, start_at, end_at) -> list[CalendarEvent]:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Calendar provider unavailable")
        return await self.provider.list_events(start_at, end_at)

    async def availability(self, request: AvailabilityRequest) -> list[AvailabilitySlot]:
        events = await self.events(request.start_at, request.end_at)
        cursor = request.start_at
        length = timedelta(minutes=request.duration_minutes)
        slots: list[AvailabilitySlot] = []
        for event in sorted(events, key=lambda item: item.start_at):
            while cursor + length <= event.start_at:
                slots.append(AvailabilitySlot(start_at=cursor, end_at=cursor + length, timezone=request.timezone))
                cursor += length
            cursor = max(cursor, event.end_at)
        while cursor + length <= request.end_at:
            slots.append(AvailabilitySlot(start_at=cursor, end_at=cursor + length, timezone=request.timezone))
            cursor += length
        return slots

    async def create(self, request: CreateEventRequest, *, approval_granted: bool) -> CalendarReceipt:
        if not approval_granted:
            raise PermissionError("Creating a calendar event is L2 and requires explicit approval")
        if request.end_at <= request.start_at:
            raise ValueError("Calendar event must end after it starts")
        receipt = await self.provider.create_event(request)
        if not receipt.verified or not receipt.event_id:
            raise RuntimeError("Calendar provider did not return a verified event ID")
        return receipt
